const { config } = require('../config');
const { relay } = require('../relay');

/**
 * Auto-translate every message posted in a mirror's source channel into its
 * destination channel.
 */
async function handleMirror(message) {
  const mirrors = (config.mirrors ?? []).filter((m) => m.fromChannelId === message.channelId);
  if (!mirrors.length) return;
  if (!message.content.trim() && message.attachments.size === 0) return;

  await Promise.all(
    mirrors.map(async (m) => {
      try {
        const channel = await message.client.channels.fetch(m.toChannelId);
        await relay({ channel, lang: m.lang, text: message.content, message });
      } catch (err) {
        console.error(`Mirror ${m.fromChannelId} -> ${m.toChannelId} failed:`, err);
      }
    }),
  );
}

module.exports = { handleMirror };
