// TypeScript compiler API scan; never evaluates project modules.
const fs = require('node:fs');
const path = require('node:path');
const ts = require(process.env.REFACTOR_TYPESCRIPT_PATH || 'typescript');
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const {safeSource} = require('./safe_source.cjs');
const records = [];
for (const name of input.files.filter(n => /\.(ts|tsx|js|jsx|mjs|cjs)$/.test(n))) {
  const absolute = safeSource(input.root, name);
  const source = ts.createSourceFile(name, fs.readFileSync(absolute, 'utf8'), ts.ScriptTarget.Latest, true);
  const line = node => source.getLineAndCharacterOfPosition(node.getStart(source)).line + 1;
  const record = {path:name, symbols:[], imports:[], calls:[], hooks:[], query_keys:[], dynamic_imports:[], route: /web\/src\/app\/.*(?:page|route)\.[tj]sx?$/.test(name), bff:name.startsWith('web/src/app/api/'), parse_errors: source.parseDiagnostics.map(d=>({code:d.code,start:d.start}))};
  function walk(node) {
    if (ts.isImportDeclaration(node) || ts.isExportDeclaration(node)) {
      if (node.moduleSpecifier && ts.isStringLiteral(node.moduleSpecifier)) record.imports.push({module:node.moduleSpecifier.text,line:line(node)});
    }
    if ((ts.isFunctionDeclaration(node) || ts.isClassDeclaration(node) || ts.isInterfaceDeclaration(node) || ts.isTypeAliasDeclaration(node)) && node.name) record.symbols.push({symbol:node.name.text,start:line(node),end:source.getLineAndCharacterOfPosition(node.end).line+1});
    if (ts.isVariableDeclaration(node) && ts.isIdentifier(node.name) && node.initializer && (ts.isArrowFunction(node.initializer)||ts.isFunctionExpression(node.initializer))) record.symbols.push({symbol:node.name.text,start:line(node),end:source.getLineAndCharacterOfPosition(node.end).line+1});
    if (ts.isCallExpression(node)) {
      const expression=node.expression;
      const callee=ts.isIdentifier(expression)?expression.text:ts.isPropertyAccessExpression(expression)?expression.name.text:expression.kind===ts.SyntaxKind.ImportKeyword?'import':'<dynamic>';
      record.calls.push({callee,line:line(node)});
      if (/^use[A-Z]/.test(callee)) record.hooks.push({callee,line:line(node)});
      if (callee==='import') record.dynamic_imports.push({line:line(node),module:node.arguments[0]&&ts.isStringLiteral(node.arguments[0])?node.arguments[0].text:'<dynamic>'});
    }
    if (ts.isPropertyAssignment(node) && node.name.getText(source)==='queryKey') record.query_keys.push({line:line(node),kind:ts.SyntaxKind[node.initializer.kind]});
    ts.forEachChild(node,walk);
  }
  walk(source);records.push(record);
}
process.stdout.write(JSON.stringify({schema_version:'typescript-inventory-v1',compiler:ts.version,files:records}));
