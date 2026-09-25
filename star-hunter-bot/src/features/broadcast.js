const { PermissionFlagsBits } = require('discord.js');
const { config } = require('../config');
const { relay } = require('../relay');

// A message counts as "tagged" if it @mentions the bot user or the bot's own role.
function mentionsBot(message) {
  const me = message.guild.members.me;
  if (message.mentions.users.has(message.client.user.id)) return true;
  const botRole = me?.roles.botRole;
  return Boolean(botRole && message.mentions.roles.has(botRole.id));
}

function stripBotMention(message) {
  const ids = [message.client.user.id, message.guild.members.me?.roles.botRole?.id].filter(Boolean);
  const pattern = new RegExp(`<@[!&]?(?:${ids.join('|')})>`, 'g');
  return message.content.replace(pattern, '').replace(/[ \t]{2,}/g, ' ').trim();
}

function canBroadcast(member, route) {
  if (member.permissions.has(PermissionFlagsBits.ManageMessages)) return true;
  const allowed = route.allowedRoleIds ?? [];
  return allowed.some((id) => member.roles.cache.has(id));
}

/**
 * When someone @mentions the bot in a broadcast source channel, send that one
 * message to every target channel, translated into each target's language.
 */
async function handleBroadcast(message) {
  const route = (config.broadcasts ?? []).find((r) => r.sourceChannelId === message.channelId);
  if (!route || !mentionsBot(message)) return false;

  if (!canBroadcast(message.member, route)) {
    await message.react('⛔').catch(() => {});
    return true;
  }

  const text = stripBotMention(message);
  if (!text && message.attachments.size === 0) return true;

  await message.react('⏳').catch(() => {});
  const results = await Promise.allSettled(
    route.targets.map(async (target) => {
      const channel = await message.client.channels.fetch(target.channelId);
      return relay({
        channel,
        lang: target.lang,
        text,
        message,
        allowedMentions: route.allowPings ? { parse: ['everyone', 'roles', 'users'] } : undefined,
      });
    }),
  );

  results.forEach((r, i) => {
    if (r.status === 'rejected') console.error(`Broadcast to ${route.targets[i].channelId} failed:`, r.reason);
  });

  await message.reactions.cache.get('⏳')?.users.remove(message.client.user.id).catch(() => {});
  const allOk = results.every((r) => r.status === 'fulfilled');
  await message.react(allOk ? '✅' : '⚠️').catch(() => {});
  return true;
}

module.exports = { handleBroadcast, stripBotMention };
