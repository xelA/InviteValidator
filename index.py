import aiohttp
import asyncio
import json

from functools import wraps
from postgreslite import PostgresLite
from quart import Quart, request, abort, render_template, redirect

from utils.api import APIHandler

with open("./config.json", "r", encoding="utf8") as f:
    config = json.load(f)

app = Quart(__name__)
db = PostgresLite("./storage.db").connect()
api = APIHandler(config, db)


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
            f"&scope=bot&redirect_uri={config['redirect_uri']}"
            "&prompt=consent&response_type=code"
        )
    )


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

    return await render_template(
        "success.html",
        name=guild_name, id=guild_id, icon=guild_icon, icon_type=icon_type,
        support=config["support_server"], website=config["bot_website"]
    )


@app.route("/error")
async def error():
    guild_id = request.args.get("guild_id", None)
    if not guild_id:
        abort(400)

    return await render_template(
        "error.html",
        guild_id=guild_id,
        support=config["support_server"]
    )


@app.route("/duplicate")
async def duplicate():
    guild_id = request.args.get("guild_id")
    if not guild_id:
        abort(400)

    return await render_template(
        "duplicate.html",
        guild_id=guild_id,
        support=config["support_server"]
    )


@app.route("/callback")
async def callback_discord():
    code = request.args.get("code", None)
    guild_id = request.args.get("guild_id", None)

    if not code:
        abort(401, "No code granted...")
    if not guild_id:
        abort(400, "Missing guild_id parameter")

    data = db.fetchrow(
        "SELECT * FROM whitelist WHERE guild_id=?",
        int(guild_id)
    )

    error_site = f"/error?guild_id={guild_id}"
    if not data:
        return redirect(error_site)
    if not data["whitelist"]:
        return redirect(error_site)
    if data["banned"]:
        return redirect(error_site)

    if data["invited"]:
        return redirect(f"/duplicate?guild_id={guild_id}")

    r = await exchange_code(code)  # Tell Discord to grant the bot
    db.execute(
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
@app.route("/api/guilds", methods=["GET", "POST", "DELETE"])
@api_validator
async def api_guild_handler():
    match request.method:
        case "GET":
            return await api.api_guild_get()
        case "POST":
            return await api.api_guild_post()
        case "DELETE":
            return await api.api_guild_delete()
        case _:
            abort(405, "Method not allowed")


@app.route("/api/guilds/ban", methods=["PUT", "DELETE"])
@api_validator
async def api_guild_ban_handler():
    match request.method:
        case "PUT":
            return await api.api_guild_ban()
        case "DELETE":
            return await api.api_guild_unban()
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


loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)

app.run(port=config["port"], loop=loop)
