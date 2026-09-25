const { ActionRowBuilder, ButtonBuilder, ButtonStyle, EmbedBuilder, MessageFlags } = require('discord.js');
const { config } = require('../config');

const onboarding = () => config.onboarding ?? {};
const fill = (template, member) =>
  template
    .replaceAll('{user}', `<@${member.id}>`)
    .replaceAll('{name}', member.displayName)
    .replaceAll('{server}', member.guild.name)
    .replaceAll('{rules}', onboarding().rulesChannelId ? `<#${onboarding().rulesChannelId}>` : 'the rules channel')
    .replaceAll('{roles}', onboarding().rolePicker?.channelId ? `<#${onboarding().rolePicker.channelId}>` : 'the roles channel')
    .replaceAll('{count}', String(member.guild.memberCount));

async function handleMemberJoin(member) {
  const cfg = onboarding();
  if (cfg.welcomeChannelId) {
    const channel = await member.guild.channels.fetch(cfg.welcomeChannelId).catch(() => null);
    const embed = new EmbedBuilder()
      .setColor(cfg.color ?? 0xf5c518)
      .setTitle(fill(cfg.welcomeTitle ?? 'Welcome to {server}!', member))
      .setDescription(fill(cfg.welcomeMessage ?? 'Hey {user}! Read {rules} to get started.', member))
      .setThumbnail(member.displayAvatarURL());
    if (cfg.bannerUrl) embed.setImage(cfg.bannerUrl);
    await channel?.send({ content: `<@${member.id}>`, embeds: [embed] }).catch((e) => console.error('Welcome post failed:', e));
  }
  if (cfg.dmMessage) {
    await member.send(fill(cfg.dmMessage, member)).catch(() => {}); // DMs closed; ignore
  }
}

function rulesPanel() {
  const cfg = onboarding();
  const embed = new EmbedBuilder()
    .setColor(cfg.color ?? 0xf5c518)
    .setTitle(cfg.rulesTitle ?? '📜 Server Rules')
    .setDescription((cfg.rules ?? []).map((r, i) => `**${i + 1}.** ${r}`).join('\n\n'))
    .setFooter({ text: 'Click the button below to accept the rules and unlock the server.' });
  const row = new ActionRowBuilder().addComponents(
    new ButtonBuilder().setCustomId('onb:agree').setLabel(cfg.agreeLabel ?? 'I agree').setEmoji('✅').setStyle(ButtonStyle.Success),
  );
  return { embeds: [embed], components: [row] };
}

function rolePanel() {
  const picker = onboarding().rolePicker ?? {};
  const embed = new EmbedBuilder()
    .setColor(onboarding().color ?? 0xf5c518)
    .setTitle(picker.title ?? '🎭 Pick your roles')
    .setDescription(picker.description ?? 'Click a button to add a role. Click again to remove it.');
  const buttons = (picker.roles ?? []).map((r) =>
    new ButtonBuilder().setCustomId(`onb:role:${r.roleId}`).setLabel(r.label).setStyle(ButtonStyle.Secondary).setEmoji(r.emoji ?? '🔹'),
  );
  // Discord allows 5 buttons per row and 5 rows per message.
  const rows = [];
  for (let i = 0; i < buttons.length && rows.length < 5; i += 5) rows.push(new ActionRowBuilder().addComponents(buttons.slice(i, i + 5)));
  return { embeds: [embed], components: rows };
}

async function handleButton(interaction) {
  const cfg = onboarding();
  const reply = (content) => interaction.reply({ content, flags: MessageFlags.Ephemeral });

  try {
    if (interaction.customId === 'onb:agree') {
      if (!cfg.memberRoleId) return reply('The member role is not configured yet. Ask a staff member.');
      if (interaction.member.roles.cache.has(cfg.memberRoleId)) return reply('You already accepted the rules. 👍');
      await interaction.member.roles.add(cfg.memberRoleId, 'Accepted rules');
      const next = cfg.rolePicker?.channelId ? ` Next, grab your roles in <#${cfg.rolePicker.channelId}>.` : '';
      return reply(`✅ Welcome aboard, hunter!${next}`);
    }

    if (interaction.customId.startsWith('onb:role:')) {
      const roleId = interaction.customId.split(':')[2];
      // Only toggle roles that are actually listed in the config.
      if (!(cfg.rolePicker?.roles ?? []).some((r) => r.roleId === roleId)) return reply('That role is no longer available.');
      if (interaction.member.roles.cache.has(roleId)) {
        await interaction.member.roles.remove(roleId, 'Role picker');
        return reply(`Removed <@&${roleId}>.`);
      }
      await interaction.member.roles.add(roleId, 'Role picker');
      return reply(`Added <@&${roleId}>.`);
    }
  } catch (err) {
    console.error('Onboarding button failed:', err);
    // Usually: the bot's role is below the role it's trying to give.
    return reply("I couldn't update your roles. A staff member needs to move my role above the roles I hand out.");
  }
}

module.exports = { handleMemberJoin, handleButton, rulesPanel, rolePanel };
