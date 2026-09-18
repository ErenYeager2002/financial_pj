const fs = require('node:fs');
const path = require('node:path');
function safeSource(root, name) {
  const base = path.resolve(root);
  const absolute = path.resolve(base, name);
  if (!absolute.startsWith(base + path.sep)) throw Error('UNSAFE_SOURCE_PATH');
  for (let current = absolute;; current = path.dirname(current)) {
    if (fs.lstatSync(current).isSymbolicLink()) throw Error('UNSAFE_SOURCE_PATH');
    if (current === path.dirname(current)) break;
  }
  if (!fs.statSync(absolute).isFile()) throw Error('UNSAFE_SOURCE_PATH');
  return absolute;
}
module.exports = {safeSource};
