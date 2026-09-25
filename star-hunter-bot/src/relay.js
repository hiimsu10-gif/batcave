const { EmbedBuilder } = require('discord.js');
const { translate } = require('./translator');
const { language } = require('./config');

const EMBED_LIMIT = 4096;
const IMAGE_EXT = /\.(png|jpe?g|gif|webp)(\?|$)/i;

/**
 * Translate `text` into `lang` and post it to `channel` as an embed that
 * credits the original author. Attachments are carried over.
 */
async function relay({ channel, lang, text, message, allowedMentions }) {
  const { name, flag } = language(lang);
  let body = text;
  let footer = `${flag} ${name}`;

  if (text.trim()) {
    try {
      body = (await translate(text, lang)).text;
    } catch (err) {
      console.error(`Translation to ${lang} failed:`, err.message);
      footer += ' · translation unavailable, original shown';
    }
  }

  const attachments = [...message.attachments.values()];
  const image = attachments.find((a) => a.contentType?.startsWith('image/') || IMAGE_EXT.test(a.name));
  const others = attachments.filter((a) => a !== image);
  if (others.length) body += `\n\n${others.map((a) => `📎 [${a.name}](${a.url})`).join('\n')}`;

  const member = message.member;
  const embed = new EmbedBuilder()
    .setColor(member?.displayColor || 0x5865f2)
    .setAuthor({
      name: member?.displayName ?? message.author.username,
      iconURL: (member ?? message.author).displayAvatarURL(),
    })
    .setFooter({ text: footer })
    .setTimestamp(message.createdAt);
  if (body.trim()) embed.setDescription(body.slice(0, EMBED_LIMIT));
  if (image) embed.setImage(image.url);

  return channel.send({ embeds: [embed], allowedMentions: allowedMentions ?? { parse: [] } });
}

module.exports = { relay };
