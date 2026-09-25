# Star Hunter | Last Order: Discord Bot

Onboarding and translation bot for the **Star Hunter | Last Order** Discord server.

## What it does

| Feature | How it works |
|---|---|
| **Tagged broadcast** | In your staff/draft channel, write a message and **@mention the bot**. The bot sends *only that message* to every target channel, translated into each channel's language (e.g. English to `#announcements`, Spanish to `#anuncios`). It reacts ⏳ then ✅ (or ⚠️ if a channel failed, ⛔ if you're not allowed). Messages without the @mention are ignored. |
| **Channel mirror** | Every message in a source channel is automatically translated into a destination channel (e.g. `#general` to `#general-es`). Optional; leave `mirrors` empty to turn it off. |
| **Onboarding** | Welcome post and DM for new members, a rules panel with an **I agree** button that gives the Member role, and a button role picker (language, playstyle, pings). |
| **/translate** | Quick private translation for anyone: `/translate text:... to:Español`. |

Translation uses **DeepL**. @mentions, custom emoji, timestamps, links and code blocks are protected, so they come through unchanged. The bot's own @mention is removed before sending.

## Setup

### 1. Create the Discord bot
1. Go to <https://discord.com/developers/applications>, click **New Application**, and name it (e.g. *Star Hunter Bot*).
2. **Bot** tab: click **Reset Token** and copy it (this is your `DISCORD_TOKEN`).
3. On the same tab, turn on **Server Members Intent** and **Message Content Intent**.
4. **OAuth2 → URL Generator**: tick scopes `bot` and `applications.commands`. Tick permissions *View Channels, Send Messages, Embed Links, Attach Files, Read Message History, Add Reactions, Manage Roles*. Open the URL and add the bot to your server.
5. **Server Settings → Roles**: drag the bot's role **above** the Member, language and playstyle roles. Otherwise it can't hand those roles out.

### 2. Get a DeepL key
Sign up at <https://www.deepl.com/pro-api> (the free plan gives 500,000 characters a month). Copy the key; free keys end in `:fx`.

### 3. Configure
```bash
cd star-hunter-bot
npm install
cp .env.example .env                                   # paste DISCORD_TOKEN and DEEPL_API_KEY
cp config/star-hunter.example.json config/star-hunter.json
```
`config/star-hunter.json` gets committed so your host can read it. `.env` stays private.
In Discord, go to **User Settings → Advanced** and turn on **Developer Mode**. Then right-click a server, channel or role and choose **Copy ID**. Replace every `PASTE_..._ID` in `config/star-hunter.json`. Delete any sections you don't need, like `mirrors` or roles you don't want in the picker.

### 4. Run
```bash
npm start
```
Then, as an admin in Discord:
- In `#rules`, run `/setup panel:Rules` to post the rules and the **I agree** button.
- In `#roles`, run `/setup panel:Role picker` to post the role buttons.

**Recommended permissions:** make most channels visible only to the **Member** role. `#welcome` and `#rules` stay visible to `@everyone`. New people then have to click **I agree** before they see the rest of the server. Show `#anuncios` / `#general-es` to the **Español** role, or to everyone.

## Adding more languages later
1. Add the language to `languages` in the config, using a [DeepL language code](https://developers.deepl.com/docs/getting-started/supported-languages):
   ```json
   "PT-BR": { "name": "Português", "flag": "🇧🇷" }
   ```
2. Add a target to your broadcast: `{ "channelId": "...", "lang": "PT-BR" }`. Optionally add a mirror, a role-picker button, or both.
3. Restart the bot.

Common codes: `EN-US`, `EN-GB`, `ES`, `PT-BR`, `FR`, `DE`, `IT`, `JA`, `KO`, `ZH`, `RU`, `TR`, `PL`, `ID`.

## Config reference
- `broadcasts[]`: `sourceChannelId`; `targets[]` (`channelId` + `lang`); `allowedRoleIds` (who can broadcast; anyone with *Manage Messages* always can); `allowPings` (set `true` to let `@everyone` and role pings in the original also ping in the target channels).
- `mirrors[]`: `fromChannelId`, `toChannelId`, `lang`. Bot messages are never mirrored, so there are no loops.
- `onboarding`: welcome text supports `{user}`, `{name}`, `{server}`, `{rules}`, `{roles}` and `{count}`. `color` is a decimal number; `bannerUrl` is an optional image.

## Running a second server
The code isn't tied to one server. For your second server, create a second bot in the Developer Portal. Then make `config/other-server.json` and run another copy with its own `.env` (`DISCORD_TOKEN=...`, `BOT_CONFIG=config/other-server.json`).

## Hosting (Railway, deploys from GitHub)
GitHub itself can't keep a bot online. Actions jobs stop after 6 hours and aren't meant to be servers. Railway runs the bot 24/7 and redeploys every time you push to GitHub.

1. Commit your filled-in `config/star-hunter.json`. Server, channel and role IDs are not secret. **Never commit `.env` or your token.**
2. Go to <https://railway.com>, sign in with GitHub, then **New Project → Deploy from GitHub repo → `batcave`**.
3. In the service **Settings**, set **Root Directory** to `star-hunter-bot`. The start command is `npm start`, which Railway picks up automatically.
4. In **Variables**, add `DISCORD_TOKEN` and `DEEPL_API_KEY`.
5. Deploy. The logs should show `Logged in as ...` and `Registered slash commands in Star Hunter | Last Order`.

If your token ever leaks (pasted in a chat, committed, screenshotted), go to Developer Portal → Bot → **Reset Token** and update the Railway variable.

Other options: a small VPS, or your own PC with [`pm2`](https://pm2.keymetrics.io/) (`pm2 start src/index.js --name star-hunter`). A PC only works while it's on.

## Development
`npm run check` runs a syntax check and the test for mention and link protection.
