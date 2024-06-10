import re
import time

from quart import request, abort, jsonify
from datetime import datetime, timedelta
from postgreslite import PoolConnection


class APIHandler:
    def __init__(self, config: dict, db: PoolConnection):
        self.config = config
        self.db = db

    async def _parse_data(self, *args) -> dict:
        """ Parse data from a dictionary """
        data = await request.json

        missing = [
            key for key in args
            if key not in data
        ]

        if missing:
            abort(400, f"Missing {', '.join(missing)}")

        for g in data:
            if g.endswith("_id"):
                self.discord_id_validator(data[g], g)

        return {key: data[key] for key in args}

    def discord_id_validator(self, guild_id: int, type: str):
        checker = re.compile(r"^[0-9]{15,19}\b").match(str(guild_id))
        if not checker:
            abort(400, f"Invalid Discord ID: {type}")

    def json_response(self, name: str, desc: str, code: int = 200):
        """ Returns a default JSON output for all API/error endpoints """
        return jsonify({"code": code, "name": name, "description": desc}), code

    async def api_guild_get(self):
        json_data = await self._parse_data("guild_id")

        data = await self.db.fetchrow(
            "SELECT * FROM whitelist WHERE guild_id=?",
            int(json_data["guild_id"])
        )

        if not data:
            return self.json_response(
                "Not found",
                "GuildID is not listed inside the API",
                404
            )

        to_send = {
            "guild_id": data["guild_id"],
            "invited": True if data["invited"] == 1 else False,
            "user_id": data["user_id"],
            "banned": {}  # Placeholder
        }

        if data["banned"]:
            to_send["banned"] = {
                "reason": data["banned_reason"],
                "user_id": data["banned_by"]
            }

        return jsonify(to_send)

    async def api_guild_post(self):
        json_data = await self._parse_data("guild_id", "user_id")

        data = await self.db.fetchrow(
            "SELECT * FROM whitelist WHERE guild_id=?",
            int(json_data["guild_id"])
        )

        if data:
            if data["banned"]:
                return self.json_response(
                    "Guild is banned",
                    f"Reason: {data['banned_reason']}",
                    403
                )

            await self.db.execute(
                "UPDATE whitelist SET user_id=?, invited=false "
                "WHERE guild_id=?",
                int(json_data["user_id"]), int(json_data["guild_id"])
            )

            return self.json_response(
                "Successfully granted",
                "GuildID has been granted invite access, again."
            )

        await self.db.execute(
            "INSERT INTO whitelist (guild_id, user_id) VALUES (?, ?)",
            int(json_data["guild_id"]), int(json_data["user_id"])
        )

        return self.json_response(
            "Successfully granted",
            "GuildID has been granted invite access"
        )

    async def api_guild_delete(self):
        json_data = await self._parse_data("guild_id", "user_id")

        data = await self.db.fetchrow(
            "SELECT * FROM whitelist WHERE guild_id=?",
            int(json_data["guild_id"])
        )

        if not data:
            return self.json_response(
                "Task refused",
                "GuildID is not even listed inside the API..."
            )

        if data["banned"]:
            return self.json_response(
                "Guild is banned",
                f"Reason: {data['banned_reason']}",
                403
            )

        await self.db.execute(
            "DELETE FROM whitelist WHERE guild_id=?",
            int(json_data["guild_id"])
        )

        return self.json_response(
            "Successfully revoked",
            "GuildID has been revoked invite access"
        )

    async def api_guild_ban(self):
        json_data = await self._parse_data(
            "guild_id", "user_id", "reason", "expires"
        )

        data = await self.db.fetchrow(
            "SELECT * FROM blacklist WHERE guild_id=?",
            int(json_data["guild_id"])
        )

        if data:
            return self.json_response(
                "Blacklist found",
                "GuildID is already blacklisted",
                404
            )

        expires = None
        expires_text = "never"
        if isinstance(json_data["expires"], int):
            expires = datetime.utcnow() + timedelta(seconds=json_data["expires"])
            expires_text = f"<t:{int(time.time() + json_data['expires'])}:R>"

        await self.db.execute(
            "INSERT INTO blacklist (guild_id, user_id, reason, expires_at) "
            "VALUES (?, ?, ?, ?)",
            int(json_data["guild_id"]), int(json_data["user_id"]),
            str(json_data["reason"]), expires
        )

        return self.json_response(
            "Successfully blacklisted",
            "GuildID has been blacklisted from the API, "
            f"expires: {expires_text}"
        )

    async def api_guild_unban(self):
        json_data = await self._parse_data("guild_id")

        data = await self.db.fetchrow(
            "SELECT * FROM blacklist WHERE guild_id=?",
            int(json_data["guild_id"])
        )

        if not data:
            return self.json_response(
                "Not found",
                "GuildID is not blacklisted inside the API",
                404
            )

        await self.db.execute(
            "DELETE FROM blacklist WHERE guild_id=?",
            int(json_data["guild_id"])
        )

        return self.json_response(
            "Successfully unbanned",
            "GuildID has been unbanned from the API"
        )
