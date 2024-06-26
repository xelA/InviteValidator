import aiohttp
import asyncio
import json
import secrets
import time

from functools import wraps
from postgreslite import PostgresLite
from datetime import timedelta
from quart import Quart, request, abort, render_template, redirect

from utils import default
from utils.api import APIHandler

with open("./config.json", "r", encoding="utf8") as f:
    config = json.load(f)

loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)

app = Quart(__name__)
db = PostgresLite("./storage.db", loop=loop).connect_async()
api = APIHandler(config, db)


async def remove_expired_blacklist():
    """ Remove expired blacklist entries """
    while True:
        await db.execute(
            "DELETE FROM blacklist WHERE expires_at < ?",
            default.legacy_utcnow()
        )
        await asyncio.sleep(30)  # Check every half minute


async def remove_expired_states():
    while True:
        await db.execute(
            "DELETE FROM states WHERE expires_at < ?",
            default.legacy_utcnow()
        )
        await asyncio.sleep(5)  # Check every 5 seconds


async def generate_state_key(integration_type: int) -> str:
    random_key = f"{secrets.token_hex(8)}-{int(time.time())}"
    await db.execute(
        "INSERT INTO states (key, integration_type, expires_at) VALUES (?, ?, ?)",
        random_key,
        integration_type,
        default.legacy_utcnow() + timedelta(minutes=1)
    )
    return random_key


async def invalidate_state_key(key: str):
    await db.execute(
        "DELETE FROM states WHERE key=?",
        key
    )


async def _discord_api_request(path: str, data: dict):
    try:
        session = aiohttp.ClientSession()
        async with session.post(f"{config['api_endpoint']}{path}", data=data) as s:
            r = await s.json()
        await session.close()
    except Exception:
        abort(500, "Server failed to connect with discord.com API")

    return r


async def exchange_code(code: str):
    """ Sends request to discord.com to grant invite request """
    r = await _discord_api_request("/oauth2/token", {
        "client_id": config["client_id"],
        "client_secret": config["client_secret"],
        "grant_type": "authorization_code",
        "redirect_uri": config["redirect_uri"],
        "scope": config["scopes"],
        "code": code
    })

    if "error" in r:
        abort(400, r["error_description"])

    return r


def api_validator(f):
    """ Validate if user can use invite API """
    @wraps(f)
    async def decorator(*args, **kwargs):
        auth = request.headers.get("Authorization", None)
        content = request.headers.get("Content-Type", None)

        if content != "application/json":
            abort(400, "Invalid Content-Type. Must be application/json")
        if not auth:
            abort(400, "Missing Authorization")

        if auth != config["backend_api_token"]:
            abort(403, "Access denied...")

        return await f(*args, **kwargs)

    return decorator


@app.route("/")
async def index():
    return await render_template(
        "index.html",
        permissions=config.get("permissions", 8),
        oauth_url=(
            f"https://discord.com/oauth2/authorize?client_id={config['client_id']}"
            f"&scope=applications.commands&redirect_uri={config['redirect_uri']}"
            "&prompt=consent&response_type=code"
        )
    )


@app.route("/oauth2/guild")
async def oauth2_guild():
    state = await generate_state_key(0)
    permissions = request.args.get("permissions", 0)
    return redirect(
        f"https://discord.com/oauth2/authorize?client_id={config['client_id']}"
        f"&scope=bot&redirect_uri={config['redirect_uri']}"
        f"&prompt=consent&response_type=code&permissions={permissions}&state={state}"
    )


@app.route("/oauth2/user")
async def oauth2_user():
    state = await generate_state_key(1)
    return redirect(
        f"https://discord.com/oauth2/authorize?client_id={config['client_id']}"
        f"&scope=applications.commands&redirect_uri={config['redirect_uri']}"
        f"&prompt=consent&response_type=code&integration_type=1&state={state}"
    )


@app.route("/success")
async def success_guild():
    guild_name = request.args.get("guild_name")
    guild_id = request.args.get("guild_id")
    guild_icon = request.args.get("guild_icon")

    if not guild_name or not guild_id:
        return abort(400)

    icon_type = "png"
    if guild_icon:
        icon_type = "gif" if guild_icon.startswith("a_") else "png"

    return await render_template(
        "success.html",
        name=guild_name, id=guild_id, icon=guild_icon, icon_type=icon_type,
        support=config["support_server"], website=config["bot_website"]
    )


@app.route("/success_user")
async def success_user():
    return await render_template(
        "success_user.html",
        support=config["support_server"],
        website=config["bot_website"]
    )


@app.route("/error")
async def error():
    guild_id = request.args.get("guild_id", None)
    code = request.args.get("code", None)
    if not guild_id or not code:
        abort(400, "Missing parameters needed for error page")

    return await render_template(
        "error.html",
        code=code,
        guild_id=guild_id,
        support=config["support_server"]
    )


@app.route("/callback")
async def callback_discord():
    code = request.args.get("code", None)
    guild_id = request.args.get("guild_id", None)
    state = request.args.get("state", None)

    if not code:
        abort(401, "No code granted...")
    if not state:
        abort(401, "No state granted...")

    data_state = await db.fetchrow(
        "SELECT * FROM states WHERE key=?",
        state
    )

    if not data_state:
        abort(401, "Invalid state... what are you doing here?")

    # Instantly invalidate the state key
    # to prevent any further usage of it
    await invalidate_state_key(state)

    if data_state["integration_type"] == 1:
        if guild_id:
            abort(400, "Unexpected guild_id parameter for user integration")

        r = await exchange_code(code)  # Tell Discord to grant user bot access
        return redirect("/success_user")

    if not guild_id:
        abort(400, "Missing guild_id parameter")

    data_whitelist = await db.fetchrow(
        "SELECT * FROM whitelist WHERE guild_id=?",
        int(guild_id)
    )

    data_blacklist = await db.fetchrow(
        "SELECT * FROM blacklist WHERE guild_id=?",
        int(guild_id)
    )

    error_site = f"/error?guild_id={guild_id}"

    if data_blacklist:
        return redirect(f"{error_site}&code=BL")
    if not data_whitelist:
        return redirect(f"{error_site}&code=NF")
    if data_whitelist["invited"]:
        return redirect(f"{error_site}&code=DUP")

    r = await exchange_code(code)  # Tell Discord to grant the bot

    await db.execute(
        "UPDATE whitelist SET invited=true WHERE guild_id=?",
        guild_id  # Guild can no longer invite bot
    )

    add_guild_icon = (
        f"&guild_icon={r['guild']['icon']}"
        if r['guild']['icon'] else ""
    )

    return redirect(
        f"/success?guild_name={r['guild']['name']}"
        f"&guild_id={guild_id}{add_guild_icon}"
    )


# API Routes
@app.route(
    "/api/guilds/<int:guild_id>",
    methods=["GET", "POST", "DELETE"]
)
@api_validator
async def api_guild_handler(guild_id: int):
    api.discord_id_validator(guild_id, "guild_id")

    match request.method:
        case "GET":
            return await api.api_guild_get(guild_id)
        case "POST":
            return await api.api_guild_post(guild_id)
        case "DELETE":
            return await api.api_guild_delete(guild_id)
        case _:
            abort(405, "Method not allowed")


@app.route("/api/bans", methods=["GET"])
@api_validator
async def api_list_bans():
    return await api.api_guild_get_bans()


@app.route(
    "/api/guilds/<int:guild_id>/bans",
    methods=["PUT", "DELETE"]
)
@api_validator
async def api_guild_ban_handler(guild_id: int):
    api.discord_id_validator(guild_id, "guild_id")

    match request.method:
        case "PUT":
            return await api.api_guild_ban(guild_id)
        case "DELETE":
            return await api.api_guild_unban(guild_id)
        case _:
            abort(405, "Method not allowed")


@app.route(
    "/api/guilds/<int:guild_id>/notes",
    methods=["GET", "PUT", "DELETE"]
)
@api_validator
async def api_guild_note_handler(guild_id: int):
    api.discord_id_validator(guild_id, "guild_id")

    match request.method:
        case "GET":
            return await api.api_guild_get_notes(guild_id)
        case "PUT":
            return await api.api_guild_add_note(guild_id)
        case "DELETE":
            return await api.api_guild_delete_note(guild_id)
        case _:
            abort(405, "Method not allowed")


@app.errorhandler(Exception)
async def handle_exception(e):
    status_code = 404
    if hasattr(e, "status_code"):
        status_code = e.status_code

    return api.json_response(
        e.name, e.description, status_code
    )


# Run background tasks before boot
loop.create_task(remove_expired_blacklist())
loop.create_task(remove_expired_states())

# Run the app
app.run(port=config["port"], loop=loop)
