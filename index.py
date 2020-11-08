import json
import asyncio
import re

from quart import Quart, request, abort, jsonify, render_template, redirect
from utils import http, sqlite

app = Quart(__name__)
db = sqlite.Database()
db.create_tables()  # Attempt to make tables

with open("config.json") as f:
    config = json.load(f)


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
        r = await http.post(f"{config['api_endpoint']}/oauth2/token", data=data, res_method="json")
    except RuntimeError:
        abort(500, "Server failed to connect with discord.com API")

    if "error" in r:
        abort(400, r["error_description"])

    return r


def api_validator():
    """ Validate if user can use invite API """
    auth = request.headers.get("Authorization")
    author_id = request.headers.get("x-responsible")
    print(request.headers)
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
    """ Check if guild is whitelisted """
    data = db.fetchrow("SELECT * FROM whitelist WHERE guild_id=?", (guild_id,))
    if not data:
        return False

    return True if data["whitelist"] == 1 else False


@app.route("/")
async def index():
    return await render_template("index.html",
        client_id=config["client_id"], redirect=config["redirect_uri"]
    )


@app.route("/api/grant/<guild_id>")
async def api_grant(guild_id):
    api_validator()
    discord_id_validator(guild_id, "guild_id")
    author_id = request.headers.get("x-responsible")

    data = db.fetchrow("SELECT * FROM whitelist WHERE guild_id=?", (int(guild_id),))
    if data:
        db.execute(
            "UPDATE whitelist SET granted_by=?, revoked_by=null, whitelist=true WHERE guild_id=?",
            (int(author_id), int(guild_id))
        )
        return json_response("Success", "GuildID has been whitelisted again")
    else:
        db.execute(
            "INSERT INTO whitelist (guild_id, granted_by) VALUES (?, ?)",
            (int(guild_id), int(author_id))
        )
        return json_response("Success", "GuildID has been whitelisted")


@app.route("/api/revoke/<guild_id>")
async def api_revoke(guild_id):
    api_validator()
    discord_id_validator(guild_id, "guild_id")
    author_id = request.headers.get("x-responsible")

    data = db.fetchrow("SELECT * FROM whitelist WHERE guild_id=?", (int(guild_id),))
    if not data:
        return "null"

    db.execute(
        "UPDATE whitelist SET revoked_by=?, whitelist=false WHERE guild_id=?",
        (int(author_id), int(guild_id))
    )
    return json_response("Success", "GuildID has been blacklisted")


@app.route("/api/guilds")
async def api_guild_list():
    api_validator()
    data = db.fetch("SELECT * FROM whitelist")
    guild_list = []
    for g in data:
        guild_list.append({
            "guild_id": g["guild_id"],
            "whitelist": True if g["whitelist"] == 1 else False,
            "granted_by": g["granted_by"],
            "revoked_by": g["revoked_by"]
        })

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


@app.route("/callback")
async def callback_discord():
    code = request.args.get("code")
    guild_id = request.args.get("guild_id")
    if not code:
        return abort(403, "No code granted...")
    if not guild_id:
        return abort(400, "Missing guild_id paramter")

    whitelist_check = whitelisted_guild(guild_id)
    if not whitelist_check:
        return abort(403, "This server is not whitelisted...")

    data = await exchange_code(code)

    add_guild_icon = f"&guild_icon={data['guild']['icon']}" if data['guild']['icon'] else ""
    return redirect(f"/success?guild_name={data['guild']['name']}&guild_id={guild_id}{add_guild_icon}")


@app.errorhandler(Exception)
async def handle_exception(e):
    return json_response(e.name, e.description, e.status_code)


loop = asyncio.get_event_loop()
app.run(port=config["port"], loop=loop)
