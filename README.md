# xelA Invite Validator
This application (website) is used to validate if xelA is allowed to be invited in servers. The main purpose of not allowing anyone to invite xelA is to avoid servers that only add bots for no reasons.

# Setup
1. Use Python 3.6 or higher
2. Install requirements.txt
3. Rename config.json.example to config.json and fill out needed information
4. Boot the website up

# API endpoints
X-Responsible: Your AuthorID
Authorization: backend_api_token from config.json

GET /api/grant/:guild_id | Grant GuildID access to invite bot
GET /api/revoke/:guild_id | Revoke GuildID access to invite bot
GET /api/guilds | Show all Guilds

# Support
You can find me at https://discord.gg/DpxkY3x if you need help, but keep in mind that I won't spoonfeed you...
