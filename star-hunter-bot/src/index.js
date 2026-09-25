require('dotenv').config({ quiet: true });
const { Client, Events, GatewayIntentBits, Partials } = require('discord.js');
const { config, configPath } = require('./config');
const { handleBroadcast } = require('./features/broadcast');
const { handleMirror } = require('./features/mirror');
const { handleMemberJoin, handleButton } = require('./features/onboarding');
const { registerCommands, handleCommand } = require('./commands');

const client = new Client({
  intents: [
    GatewayIntentBits.Guilds,
    GatewayIntentBits.GuildMembers, // privileged: member join events
    GatewayIntentBits.GuildMessages,
    GatewayIntentBits.MessageContent, // privileged: read message text
  ],
  partials: [Partials.GuildMember],
});

client.once(Events.ClientReady, async (c) => {
  console.log(`Logged in as ${c.user.tag} using ${configPath}`);
  await registerCommands(c).catch((e) => console.error('Slash command registration failed:', e));
});

client.on(Events.MessageCreate, async (message) => {
  if (message.author.bot || !message.inGuild() || message.guildId !== config.guildId) return;
  try {
    // A tagged broadcast message is handled once, not also mirrored.
    if (await handleBroadcast(message)) return;
    await handleMirror(message);
  } catch (err) {
    console.error('Message handling failed:', err);
  }
});

client.on(Events.GuildMemberAdd, (member) => {
  if (member.guild.id === config.guildId) handleMemberJoin(member).catch((e) => console.error('Join handler failed:', e));
});

client.on(Events.InteractionCreate, async (interaction) => {
  try {
    if (interaction.isChatInputCommand()) await handleCommand(interaction);
    else if (interaction.isButton() && interaction.customId.startsWith('onb:')) await handleButton(interaction);
  } catch (err) {
    console.error('Interaction failed:', err);
  }
});

client.login(process.env.DISCORD_TOKEN);
