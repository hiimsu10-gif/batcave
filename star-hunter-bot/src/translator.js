const deepl = require('deepl-node');

let client;

function getClient() {
  if (!client) {
    if (!process.env.DEEPL_API_KEY) throw new Error('DEEPL_API_KEY is not set');
    client = new deepl.DeepLClient(process.env.DEEPL_API_KEY);
  }
  return client;
}

// Discord tokens that must survive translation untouched: user/role/channel
// mentions, custom emoji, timestamps, URLs, and inline/block code.
const PROTECTED = /```[\s\S]*?```|`[^`\n]+`|<a?:\w+:\d+>|<(?:@[!&]?|#)\d+>|<t:\d+(?::[a-zA-Z])?>|https?:\/\/\S+/g;

const escapeXml = (s) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
const unescapeXml = (s) => s.replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&amp;/g, '&');

// Swap protected tokens for <x i="N"/> placeholders so DeepL leaves them alone.
function protect(text) {
  const tokens = [];
  let out = '';
  let last = 0;
  for (const match of text.matchAll(PROTECTED)) {
    out += escapeXml(text.slice(last, match.index)) + `<x i="${tokens.length}"/>`;
    tokens.push(match[0]);
    last = match.index + match[0].length;
  }
  out += escapeXml(text.slice(last));
  return { xml: out, tokens };
}

function restore(xml, tokens) {
  const withTokens = xml.replace(/<x i="(\d+)"\s*\/>/g, (_, i) => `\u0000${i}\u0000`);
  return unescapeXml(withTokens).replace(/\u0000(\d+)\u0000/g, (_, i) => tokens[Number(i)] ?? '');
}

/**
 * Translate text into a DeepL target language code (e.g. "ES", "EN-US", "PT-BR").
 * Returns { text, detectedSourceLang }.
 */
async function translate(text, targetLang) {
  if (!text.trim()) return { text, detectedSourceLang: null };
  const { xml, tokens } = protect(text);
  const result = await getClient().translateText(xml, null, targetLang, {
    tagHandling: 'xml',
    ignoreTags: ['x'],
    preserveFormatting: true,
  });
  return { text: restore(result.text, tokens), detectedSourceLang: result.detectedSourceLang };
}

module.exports = { translate, protect, restore };
