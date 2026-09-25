const assert = require('node:assert');
const { protect, restore } = require('../src/translator');

const cases = [
  'Raid tonight at <t:1767225600:t> with <@123456789> and <@&987654321> in <#555>!',
  'Patch notes: https://example.com/notes?a=1&b=2 <:star:112233> <a:spin:445566>',
  'Use `/lfg` or ```\ncode <x>\n``` and 5 > 3 & 2 < 4',
];

for (const text of cases) {
  const { xml, tokens } = protect(text);
  assert.ok(!/<@|<#|https?:/.test(xml.replace(/<x i="\d+"\/>/g, '')), `tokens leaked: ${xml}`);
  // Simulate DeepL returning the XML unchanged (it may also add a space before "/>").
  assert.strictEqual(restore(xml.replace(/"\/>/g, '" />'), tokens), text);
}
console.log('translator tests passed');
