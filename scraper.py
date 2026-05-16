import asyncio
import csv
import io
import os
from datetime import datetime
from telethon.tl.functions.channels import GetParticipantsRequest, InviteToChannelRequest
from telethon.tl.functions.messages import AddChatUserRequest
from telethon.tl.types import (
    ChannelParticipantsSearch, ChannelParticipantsAdmins,
    UserStatusRecently, UserStatusOnline,
    Channel, Chat, User
)
from telethon.errors import (
    FloodWaitError, UserPrivacyRestrictedError, UserNotMutualContactError,
    ChatWriteForbiddenError, InputUserDeactivatedError, UserBannedInChannelError,
    PeerFloodError, UserAlreadyParticipantError, ChatAdminRequiredError,
    ChannelPrivateError, InviteHashExpiredError
)
from database import db
from client_manager import client_manager


class Scraper:

    # ─────────────────────────────────────────────
    # EXISTING: Scrape group members (participant list)
    # ─────────────────────────────────────────────
    async def scrape_group_members(self, user_id, group_username, limit=1000):
        """Scrape members from a group (existing method — unchanged)"""
        try:
            account = await db.get_active_account(user_id)
            if not account:
                return {'success': False, 'error': 'No active account'}

            client = await client_manager.get_client(user_id, account['id'])
            if not client:
                client = await client_manager.create_client(
                    user_id, account['id'],
                    account['api_id'], account['api_hash'],
                    account['session_string']
                )

            group = await client.get_entity(group_username)

            members = []
            offset = 0

            while len(members) < limit:
                participants = await client(GetParticipantsRequest(
                    group,
                    ChannelParticipantsSearch(''),
                    offset,
                    100,
                    hash=0
                ))

                if not participants.users:
                    break

                for user in participants.users:
                    if not user.bot:
                        members.append({
                            'id': user.id,
                            'username': user.username,
                            'first_name': user.first_name,
                            'last_name': user.last_name,
                            'phone': user.phone
                        })

                offset += len(participants.users)

                if len(participants.users) < 100:
                    break

            return {
                'success': True,
                'members': members[:limit],
                'total': len(members)
            }

        except Exception as e:
            return {'success': False, 'error': str(e)}

    # ─────────────────────────────────────────────
    # EXISTING: Scrape message replies
    # ─────────────────────────────────────────────
    async def scrape_message_replies(self, user_id, group_username, message_id, limit=100):
        """Scrape users who replied to a specific message (existing — unchanged)"""
        try:
            account = await db.get_active_account(user_id)
            if not account:
                return {'success': False, 'error': 'No active account'}

            client = await client_manager.get_client(user_id, account['id'])
            if not client:
                client = await client_manager.create_client(
                    user_id, account['id'],
                    account['api_id'], account['api_hash'],
                    account['session_string']
                )

            group = await client.get_entity(group_username)
            replies = await client.get_messages(group, reply_to=message_id, limit=limit)

            users = []
            seen_ids = set()

            for reply in replies:
                if reply.sender_id and reply.sender_id not in seen_ids:
                    sender = await reply.get_sender()
                    if not sender.bot:
                        users.append({
                            'id': sender.id,
                            'username': sender.username,
                            'first_name': sender.first_name,
                            'last_name': sender.last_name
                        })
                        seen_ids.add(sender.id)

            return {'success': True, 'users': users, 'total': len(users)}

        except Exception as e:
            return {'success': False, 'error': str(e)}

    # ─────────────────────────────────────────────
    # EXISTING: Get chat messages
    # ─────────────────────────────────────────────
    async def get_chat_messages(self, user_id, chat_username, limit=100):
        """Get recent messages from a chat (existing — unchanged)"""
        try:
            account = await db.get_active_account(user_id)
            if not account:
                return {'success': False, 'error': 'No active account'}

            client = await client_manager.get_client(user_id, account['id'])
            if not client:
                client = await client_manager.create_client(
                    user_id, account['id'],
                    account['api_id'], account['api_hash'],
                    account['session_string']
                )

            messages = await client.get_messages(chat_username, limit=limit)

            message_list = []
            for msg in messages:
                message_list.append({
                    'id': msg.id,
                    'text': msg.text,
                    'sender_id': msg.sender_id,
                    'date': msg.date.isoformat()
                })

            return {'success': True, 'messages': message_list, 'total': len(message_list)}

        except Exception as e:
            return {'success': False, 'error': str(e)}

    # ─────────────────────────────────────────────
    # NEW: Scrape active users from recent messages
    # ─────────────────────────────────────────────
    async def scrape_active_users(self, user_id, group_link, message_limit=1000):
        """
        Scrape users who recently sent messages in a group.
        - Skips admins
        - Skips bots
        - Skips duplicates (also checks DB history)
        - Returns: all_users list + history_users list (those with prior DM history)
        """
        try:
            account = await db.get_active_account(user_id)
            if not account:
                return {'success': False, 'error': 'No active account'}

            client = await client_manager.get_client(user_id, account['id'])
            if not client:
                client = await client_manager.create_client(
                    user_id, account['id'],
                    account['api_id'], account['api_hash'],
                    account['session_string']
                )

            await client.connect()

            # Resolve group
            group = await client.get_entity(group_link)

            # Get admin IDs to skip
            admin_ids = set()
            try:
                admins = await client(GetParticipantsRequest(
                    group, ChannelParticipantsAdmins(), 0, 200, hash=0
                ))
                for a in admins.users:
                    admin_ids.add(a.id)
            except Exception:
                pass

            # Get already-scraped user IDs from DB (global history)
            already_scraped = await db.get_all_scraped_user_ids(user_id)
            already_scraped_set = set(already_scraped)

            # Fetch recent messages
            seen_ids = set()
            all_users = []
            history_users = []

            async for msg in client.iter_messages(group, limit=message_limit):
                if not msg.sender_id:
                    continue
                if msg.sender_id in seen_ids:
                    continue
                seen_ids.add(msg.sender_id)

                try:
                    sender = await client.get_entity(msg.sender_id)
                except Exception:
                    continue

                # Skip bots and admins
                if getattr(sender, 'bot', False):
                    continue
                if sender.id in admin_ids:
                    continue

                user_data = {
                    'id': sender.id,
                    'username': getattr(sender, 'username', None),
                    'first_name': getattr(sender, 'first_name', None) or '',
                    'last_name': getattr(sender, 'last_name', None) or '',
                    'is_new': sender.id not in already_scraped_set
                }

                all_users.append(user_data)

                # Check if we have prior DM/chat history with this user
                has_history = await self._check_chat_history(client, sender.id)
                if has_history:
                    history_users.append(user_data)

                await asyncio.sleep(0.05)  # avoid flood

            # Save new users to DB
            new_users = [u for u in all_users if u['is_new']]
            if new_users:
                await db.save_scraped_users(user_id, new_users)

            return {
                'success': True,
                'all_users': all_users,
                'history_users': history_users,
                'total': len(all_users),
                'new_count': len(new_users),
                'history_count': len(history_users)
            }

        except Exception as e:
            return {'success': False, 'error': str(e)}

    async def _check_chat_history(self, client, peer_id):
        """Check if logged-in userbot has any prior messages with this user"""
        try:
            msgs = await client.get_messages(peer_id, limit=1)
            return len(msgs) > 0
        except Exception:
            return False

    # ─────────────────────────────────────────────
    # HELPER: Detect target type & return label
    # ─────────────────────────────────────────────
    def _get_target_type(self, entity):
        """
        Returns one of:
          'broadcast_channel'  → Public/Private Channel (broadcast=True)
          'supergroup'         → Supergroup (megagroup=True)
          'legacy_group'       → Old-style Chat (not Channel)
        """
        if isinstance(entity, Channel):
            if entity.broadcast:
                return 'broadcast_channel'
            else:
                return 'supergroup'
        elif isinstance(entity, Chat):
            return 'legacy_group'
        else:
            return 'unknown'

    # ─────────────────────────────────────────────
    # FIXED: Add users — auto-detects target type
    # ─────────────────────────────────────────────
    async def add_users_to_group(self, user_id, target_group, user_ids_to_add,
                                  status_callback=None):
        """
        Smart add — works for ALL target types:

        ┌─────────────────────┬──────────────────────────────────────┐
        │ Target type         │ Method used                          │
        ├─────────────────────┼──────────────────────────────────────┤
        │ Public Group        │ InviteToChannelRequest (supergroup)  │
        │ Private Group       │ InviteToChannelRequest (supergroup)  │
        │ Public Channel      │ ⚠️ Skipped (channels need subscribe) │
        │ Private Channel     │ ⚠️ Skipped (channels need subscribe) │
        │ Legacy Chat (pvt)   │ AddChatUserRequest                   │
        └─────────────────────┴──────────────────────────────────────┘

        Handles:
        - FloodWait  → auto-sleep + retry
        - PeerFlood  → stop & report
        - Already member → skip
        - Privacy restricted → skip
        - Deactivated / banned → skip
        """
        try:
            account = await db.get_active_account(user_id)
            if not account:
                return {'success': False, 'error': 'No active account'}

            client = await client_manager.get_client(user_id, account['id'])
            if not client:
                client = await client_manager.create_client(
                    user_id, account['id'],
                    account['api_id'], account['api_hash'],
                    account['session_string']
                )

            await client.connect()

            # ── Resolve target ──────────────────────────────
            try:
                group = await client.get_entity(target_group)
            except (ChannelPrivateError, InviteHashExpiredError) as e:
                return {'success': False, 'error': f'Cannot access target: {e}'}
            except Exception as e:
                return {'success': False, 'error': f'Invalid target: {e}'}

            target_type = self._get_target_type(group)

            # Broadcast channels don't support adding members
            if target_type == 'broadcast_channel':
                return {
                    'success': False,
                    'error': (
                        '📢 Yeh ek Channel hai — channels mein directly add '
                        'nahi hota. Members sirf subscribe karte hain. '
                        'Invite link share karo.'
                    )
                }

            # ── Get already-added history from DB ───────────
            already_added = await db.get_added_user_ids(user_id, str(group.id))
            already_added_set = set(already_added)

            added = 0
            failed = 0
            skipped = 0
            peer_flood_hit = False

            for uid in user_ids_to_add:
                if uid in already_added_set:
                    skipped += 1
                    continue

                try:
                    user_entity = await client.get_entity(uid)

                    # ── Pick the right API call ─────────────
                    if target_type == 'legacy_group':
                        # Old-style group (Chat) → AddChatUserRequest
                        await client(AddChatUserRequest(
                            chat_id=group.id,
                            user_id=user_entity,
                            fwd_limit=50  # forward last 50 messages to new member
                        ))
                    else:
                        # Supergroup (public or private) → InviteToChannelRequest
                        await client(InviteToChannelRequest(group, [user_entity]))

                    await db.save_added_user(user_id, str(group.id), uid)
                    added += 1

                    if status_callback:
                        await status_callback(added, failed, skipped, None)

                    # Safe delay between adds (15–20s to avoid ban)
                    await asyncio.sleep(18)

                except UserAlreadyParticipantError:
                    skipped += 1
                    await db.save_added_user(user_id, str(group.id), uid)

                except FloodWaitError as e:
                    wait = e.seconds
                    if status_callback:
                        await status_callback(added, failed, skipped,
                                              f"⏳ FloodWait {wait}s — pausing...")
                    await asyncio.sleep(wait + 5)
                    # Retry once after flood wait
                    try:
                        if target_type == 'legacy_group':
                            await client(AddChatUserRequest(
                                chat_id=group.id,
                                user_id=user_entity,
                                fwd_limit=50
                            ))
                        else:
                            await client(InviteToChannelRequest(group, [user_entity]))
                        await db.save_added_user(user_id, str(group.id), uid)
                        added += 1
                    except Exception:
                        failed += 1

                except PeerFloodError:
                    peer_flood_hit = True
                    if status_callback:
                        await status_callback(added, failed, skipped,
                                              "🚨 PeerFlood — Telegram is rate-limiting. Stopped.")
                    break

                except ChatAdminRequiredError:
                    # Bot/account doesn't have permission to add in this group
                    return {
                        'success': False,
                        'error': (
                            '🔒 Admin permission nahi hai. '
                            'Account ko group admin banao ya "Members add" permission do.'
                        )
                    }

                except (UserPrivacyRestrictedError, UserNotMutualContactError,
                        InputUserDeactivatedError, UserBannedInChannelError):
                    failed += 1

                except Exception as e:
                    failed += 1
                    print(f"Add error for {uid}: {e}")

            return {
                'success': True,
                'added': added,
                'failed': failed,
                'skipped': skipped,
                'peer_flood': peer_flood_hit,
                'target_type': target_type
            }

        except Exception as e:
            return {'success': False, 'error': str(e)}

    # ─────────────────────────────────────────────
    # NEW: Send message to a list of user IDs
    # ─────────────────────────────────────────────
    async def blast_message_to_users(self, user_id, target_user_ids, message_text,
                                      status_callback=None):
        """
        Send a custom message to a list of Telegram user IDs.
        Handles FloodWait, privacy errors, deactivated accounts.
        """
        try:
            account = await db.get_active_account(user_id)
            if not account:
                return {'success': False, 'error': 'No active account'}

            client = await client_manager.get_client(user_id, account['id'])
            if not client:
                client = await client_manager.create_client(
                    user_id, account['id'],
                    account['api_id'], account['api_hash'],
                    account['session_string']
                )

            await client.connect()

            sent = 0
            failed = 0

            for uid in target_user_ids:
                try:
                    await client.send_message(uid, message_text)
                    sent += 1

                    if status_callback:
                        await status_callback(sent, failed, None)

                    await asyncio.sleep(5)  # safe delay between messages

                except FloodWaitError as e:
                    await asyncio.sleep(e.seconds + 5)
                    try:
                        await client.send_message(uid, message_text)
                        sent += 1
                    except Exception:
                        failed += 1

                except (UserPrivacyRestrictedError, InputUserDeactivatedError):
                    failed += 1

                except Exception as e:
                    failed += 1
                    print(f"Message error for {uid}: {e}")

            return {'success': True, 'sent': sent, 'failed': failed}

        except Exception as e:
            return {'success': False, 'error': str(e)}

    # ─────────────────────────────────────────────
    # HELPER: Parse user IDs from uploaded TXT/CSV
    # ─────────────────────────────────────────────
    def parse_user_file(self, file_content: bytes, filename: str):
        """
        Parse a TXT or CSV file and extract user IDs or usernames.
        Returns list of dicts: [{'id': ..., 'username': ...}, ...]
        """
        users = []
        try:
            text = file_content.decode('utf-8', errors='ignore')

            if filename.lower().endswith('.csv'):
                reader = csv.DictReader(io.StringIO(text))
                for row in reader:
                    uid = row.get('id') or row.get('user_id') or row.get('ID')
                    uname = row.get('username') or row.get('Username') or ''
                    if uid:
                        try:
                            users.append({'id': int(uid), 'username': uname})
                        except ValueError:
                            pass
            else:
                # Plain TXT: one entry per line, either ID or @username
                for line in text.splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    if line.startswith('@'):
                        users.append({'id': None, 'username': line.lstrip('@')})
                    else:
                        try:
                            users.append({'id': int(line), 'username': None})
                        except ValueError:
                            pass
        except Exception as e:
            print(f"File parse error: {e}")

        return users

    # ─────────────────────────────────────────────
    # HELPER: Build CSV + TXT output from user list
    # ─────────────────────────────────────────────
    def build_output_files(self, users: list, prefix: str = 'scraped'):
        """
        Returns (csv_bytes, txt_bytes) for a list of user dicts.
        """
        # CSV
        csv_out = io.StringIO()
        writer = csv.DictWriter(csv_out, fieldnames=['id', 'username', 'first_name', 'last_name'])
        writer.writeheader()
        for u in users:
            writer.writerow({
                'id': u.get('id', ''),
                'username': u.get('username', '') or '',
                'first_name': u.get('first_name', '') or '',
                'last_name': u.get('last_name', '') or ''
            })
        csv_bytes = csv_out.getvalue().encode()

        # TXT (one @username or id per line)
        txt_lines = []
        for u in users:
            if u.get('username'):
                txt_lines.append(f"@{u['username']}")
            elif u.get('id'):
                txt_lines.append(str(u['id']))
        txt_bytes = '\n'.join(txt_lines).encode()

        return csv_bytes, txt_bytes


scraper = Scraper()
