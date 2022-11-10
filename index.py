import json
import asyncio
import re
import traceback
import aiohttp

from quart import Quart, request, abort, jsonify, render_template, redirect
from utils import sqlite

app = Quart(__name__)
db = sqlite.Database()
db.create_tables()  # Attempt to make tables

loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)

with open("config.json") as f:
    config = json.load(f)


def traceback_maker(err, advance: bool = True):
    _traceback = ''.join(traceback.format_tb(err.__traceback__))
    error = ('```py\n{1}{0}: {2}\n```').format(type(err).__name__, _traceback, err)
    return error if advance else f"{type(err).__name__}: {err}"


async def exchange_code(code: str):
    """ Sends request to discord.com to grant invite request """
    data = {
        "client_id": config["client_id"],
        "client_secret": config["client_secret"],
        "grant_type": "authorization_code",
        "redirect_uri": config["redirect_uri"],
        "scope": config["scopes"],
        "code": code
    }

    try:
        session = aiohttp.ClientSession()
        async with session.post(f"{config['api_endpoint']}/oauth2/token", data=data) as s:
            r = await s.json()
        await session.close()
    except Exception:
        abort(500, "Server failed to connect with discord.com API")

    if "error" in r:
        abort(400, r["error_description"])

    return r


def api_validator():
    """ Validate if user can use invite API """
    auth = request.headers.get("Authorization")
    author_id = request.headers.get("x-responsible")
    if not auth:
        abort(400, "Missing Authorization")
    if not author_id:
        abort(400, "Missing x-responsible")
    discord_id_validator(author_id, "x-responsible")
    if auth != config["backend_api_token"]:
        abort(403, "Access denied...")


def discord_id_validator(guild_id, type: str):
    checker = re.compile(r"^[0-9]{15,19}\b").match(guild_id)
    if not checker:
        abort(400, f"Invalid Discord ID: {type}")


def json_response(name: str, desc: str, code: int = 200):
    """ Returns a default JSON output for all API/error endpoints """
    return jsonify({"code": code, "name": name, "description": desc}), code


def whitelisted_guild(guild_id: int):
    """ Check if guild is whitelisted
    Values: return( WHITELIST, INVITED )
    """
    data = db.fetchrow("SELECT * FROM whitelist WHERE guild_id=?", (guild_id,))
    return (
        (data["whitelist"] == 1, data["invited"] == 1)
        if data
        else (False, True)
    )


@app.route("/")
async def index():
    return await render_template(
        "index.html",
        permissions=config.get("permissions", 8),
        oauth_url=f"https://discord.com/oauth2/authorize?client_id={config['client_id']}"
                  f"&scope=bot&redirect_uri={config['redirect_uri']}&prompt=consent&response_type=code"
    )


@app.route("/api/guilds/<guild_id>", methods=["GET"])
async def api_guild_info(guild_id):
    api_validator()
    discord_id_validator(guild_id, "guild_id")
    data = db.fetchrow("SELECT * FROM whitelist WHERE guild_id=?", (int(guild_id),))
    return (
        jsonify(
            {
                "guild_id": data["guild_id"],
                "whitelist": data["whitelist"] == 1,
                "invited": data["invited"] == 1,
                "granted_by": data["granted_by"],
                "revoked_by": data["revoked_by"],
            }
        )
        if data
        else jsonify(
            {
                "guild_id": None,
                "whitelist": None,
                "granted_by": None,
                "revoked_by": None,
                "invited": None,
            }
        )
    )


@app.route("/api/guilds/<guild_id>", methods=["POST"])
async def api_grant(guild_id):
    api_validator()
    discord_id_validator(guild_id, "guild_id")
    author_id = request.headers.get("x-responsible")

    if data := db.fetchrow(
        "SELECT * FROM whitelist WHERE guild_id=?", (int(guild_id),)
    ):
        db.execute(
            "UPDATE whitelist SET granted_by=?, revoked_by=null, whitelist=true, invited=false WHERE guild_id=?",
            (int(author_id), int(guild_id))
        )
        return json_response("Successfully granted", "GuildID has been granted invite access, again.")
    else:
        db.execute(
            "INSERT INTO whitelist (guild_id, granted_by) VALUES (?, ?)",
            (int(guild_id), int(author_id))
        )
        return json_response("Successfully granted", "GuildID has been granted invite access")


@app.route("/api/guilds/<guild_id>", methods=["DELETE"])
async def api_revoke(guild_id):
    api_validator()
    discord_id_validator(guild_id, "guild_id")
    author_id = request.headers.get("x-responsible")

    data = db.fetchrow("SELECT * FROM whitelist WHERE guild_id=?", (int(guild_id),))
    if not data:
        return json_response("Task refused", "GuildID is not even listed inside the API...")

    db.execute(
        "UPDATE whitelist SET revoked_by=?, whitelist=false WHERE guild_id=?",
        (int(author_id), int(guild_id))
    )
    return json_response("Successfully revoked", "GuildID has been revoked invite access")


@app.route("/api/guilds", methods=["GET"])
async def api_guild_list():
    api_validator()
    data = db.fetch("SELECT * FROM whitelist")
    guild_list = [
        {
            "guild_id": g["guild_id"],
            "whitelist": g["whitelist"] == 1,
            "granted_by": g["granted_by"],
            "revoked_by": g["revoked_by"],
            "invited": g["invited"],
        }
        for g in data
    ]

    return jsonify(guild_list)


@app.route("/success")
async def success():
    guild_name = request.args.get("guild_name")
    guild_id = request.args.get("guild_id")
    guild_icon = request.args.get("guild_icon")

    if not guild_name or not guild_id:
        return abort(400)

    icon_type = "png"
    if guild_icon:
        icon_type = "gif" if guild_icon.startswith("a_") else "png"

    return await render_template("success.html",
        name=guild_name, id=guild_id, icon=guild_icon, icon_type=icon_type,
        support=config["support_server"], website=config["bot_website"]
    )


@app.route("/error")
async def error():
    guild_id = request.args.get("guild_id")
    if not guild_id:
        abort(400)
    return await render_template("error.html", guild_id=guild_id, support=config["support_server"])


@app.route("/duplicate")
async def duplicate():
    guild_id = request.args.get("guild_id")
    if not guild_id:
        abort(400)
    return await render_template("duplicate.html", guild_id=guild_id, support=config["support_server"])


@app.route("/callback")
async def callback_discord():
    code = request.args.get("code")
    guild_id = request.args.get("guild_id")
    if not code:
        return abort(401, "No code granted...")
    if not guild_id:
        return abort(400, "Missing guild_id parameter")

    whitelist_check, invited_check = whitelisted_guild(guild_id)
    if not whitelist_check:
        return redirect(f"/error?guild_id={guild_id}")
    if invited_check:
        return redirect(f"/duplicate?guild_id={guild_id}")

    data = await exchange_code(code)  # Tell Discord to grant the bot
    db.execute("UPDATE whitelist SET invited=true WHERE guild_id=?", (guild_id,))  # Guild can no longer invite bot

    add_guild_icon = f"&guild_icon={data['guild']['icon']}" if data['guild']['icon'] else ""
    return redirect(f"/success?guild_name={data['guild']['name']}&guild_id={guild_id}{add_guild_icon}")


@app.errorhandler(Exception)
async def handle_exception(e):
    status_code = e.status_code if hasattr(e, "status_code") else 404
    return json_response(e.name, e.description, status_code)


app.run(port=config["port"], loop=loop)
