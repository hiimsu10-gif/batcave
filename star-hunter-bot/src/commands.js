const { SlashCommandBuilder, PermissionFlagsBits, MessageFlags } = require('discord.js');
const { config, language } = require('./config');
const { translate } = require('./translator');
const { rulesPanel, rolePanel } = require('./features/onboarding');

const languageChoices = () =>
  Object.keys(config.languages ?? {}).slice(0, 25).map((code) => ({ name: language(code).name, value: code }));

const definitions = () => [
  new SlashCommandBuilder()
    .setName('setup')
    .setDescription('Post an onboarding panel in this channel')
    .setDefaultMemberPermissions(PermissionFlagsBits.ManageGuild)
    .addStringOption((o) =>
      o.setName('panel').setDescription('Which panel to post').setRequired(true).addChoices(
        { name: 'Rules + "I agree" button', value: 'rules' },
        { name: 'Role picker', value: 'roles' },
      ),
    ),
  new SlashCommandBuilder()
    .setName('translate')
    .setDescription('Translate some text (only you see the result)')
    .addStringOption((o) => o.setName('text').setDescription('Text to translate').setRequired(true))
    .addStringOption((o) => o.setName('to').setDescription('Target language').setRequired(true).addChoices(...languageChoices())),
];

async function registerCommands(client) {
  const guild = await client.guilds.fetch(config.guildId);
  await guild.commands.set(definitions().map((d) => d.toJSON()));
  console.log(`Registered slash commands in ${guild.name}`);
}

async function handleCommand(interaction) {
  if (interaction.commandName === 'setup') {
    const panel = interaction.options.getString('panel') === 'rules' ? rulesPanel() : rolePanel();
    await interaction.channel.send(panel);
    return interaction.reply({ content: 'Panel posted.', flags: MessageFlags.Ephemeral });
  }

  if (interaction.commandName === 'translate') {
    await interaction.deferReply({ flags: MessageFlags.Ephemeral });
    const to = interaction.options.getString('to');
    try {
      const { text } = await translate(interaction.options.getString('text'), to);
      const { flag, name } = language(to);
      return interaction.editReply(`${flag} **${name}:** ${text}`);
    } catch (err) {
      console.error('/translate failed:', err);
      return interaction.editReply('Translation failed. Check the DeepL key and quota.');
    }
  }
}

module.exports = { registerCommands, handleCommand };
