// Structural evidence only: no module execution or prompt/config value dumping.
function classify(ts, source, name) {
  const out = {components: [], jsx_references: [], model_call_candidates: [], query_key_shapes: [], style_imports: [], build_config: /(?:^|\/)(?:next|tailwind|postcss|vite|vitest|eslint|prettier|webpack)\.config\./.test(name)};
  const line = n => source.getLineAndCharacterOfPosition(n.getStart(source)).line + 1;
  function symbol(n) {
    if (ts.isIdentifier(n)) return n.text;
    if (ts.isPropertyAccessExpression(n)) return symbol(n.expression) + '.' + n.name.text;
    return '<dynamic>';
  }
  function shape(n) {
    if (ts.isArrayLiteralExpression(n)) return {kind:'array', items:n.elements.map(shape)};
    if (ts.isIdentifier(n) || ts.isPropertyAccessExpression(n)) return {kind:'reference', symbol:symbol(n)};
    if (ts.isCallExpression(n)) return {kind:'factory', symbol:symbol(n.expression), arguments:n.arguments.map(shape)};
    if (ts.isStringLiteral(n) || ts.isNumericLiteral(n) || ts.isNoSubstitutionTemplateLiteral(n)) return {kind:'literal', type:ts.SyntaxKind[n.kind]};
    return {kind:ts.SyntaxKind[n.kind]};
  }
  function owner(n) {
    for (let current = n.parent; current; current = current.parent) {
      if (ts.isFunctionDeclaration(current)) return current.name?.text || '<anonymous>';
      if (ts.isArrowFunction(current) || ts.isFunctionExpression(current)) {
        return ts.isVariableDeclaration(current.parent) && ts.isIdentifier(current.parent.name) ? current.parent.name.text : '<anonymous>';
      }
    }
    return '<module>';
  }
  const imports = new Map();
  const instances = new Map();
  const modelModule = m => /^(?:(?:openai|@anthropic-ai\/sdk|@google\/generative-ai|@google\/genai|ai)(?:\/|$)|@ai-sdk\/|@(?:mariozechner|earendil-works)\/pi-)/.test(m);
  function bindings(n) {
    if (ts.isImportDeclaration(n) && ts.isStringLiteral(n.moduleSpecifier)) {
      const module = n.moduleSpecifier.text;
      if (/\.(?:css|scss|sass|less)$/.test(module)) out.style_imports.push({module,line:line(n)});
      const clause = n.importClause;
      if (clause?.name) imports.set(clause.name.text,{module, imported:'default'});
      if (clause?.namedBindings) {
        if (ts.isNamespaceImport(clause.namedBindings)) imports.set(clause.namedBindings.name.text,{module, imported:'*'});
        else for (const element of clause.namedBindings.elements) imports.set(element.name.text,{module, imported:(element.propertyName || element.name).text});
      }
    }
    ts.forEachChild(n,bindings);
  }
  bindings(source);
  function constructors(n) {
    if (ts.isVariableDeclaration(n) && ts.isIdentifier(n.name) && n.initializer && ts.isNewExpression(n.initializer)) {
      const root = symbol(n.initializer.expression).split('.')[0];
      const imported = imports.get(root);
      if (imported && modelModule(imported.module)) instances.set(n.name.text,imported);
    }
    ts.forEachChild(n,constructors);
  }
  constructors(source);
  const seenComponents = new Set();
  function walk(n) {
    if (ts.isJsxOpeningElement(n) || ts.isJsxSelfClosingElement(n) || ts.isJsxOpeningFragment(n)) {
      const component = owner(n);
      if (/^[A-Z]/.test(component) && !seenComponents.has(component)) {
        seenComponents.add(component);out.components.push({symbol:component,evidence:'contains-jsx',line:line(n)});
      }
      if (n.tagName) out.jsx_references.push({symbol:symbol(n.tagName),owner:component,line:line(n)});
    }
    if (ts.isPropertyAssignment(n) && ((ts.isIdentifier(n.name) || ts.isStringLiteral(n.name)) && n.name.text === 'queryKey')) out.query_key_shapes.push({line:line(n),shape:shape(n.initializer)});
    if (ts.isShorthandPropertyAssignment(n) && n.name.text === 'queryKey') out.query_key_shapes.push({line:line(n),shape:shape(n.name)});
    if (ts.isCallExpression(n)) {
      const callee=symbol(n.expression), root=callee.split('.')[0];
      const imported=imports.get(root) || instances.get(root);
      if (imported && modelModule(imported.module)) out.model_call_candidates.push({callee,line:line(n),binding:imported,evidence:instances.has(root)?'sdk-instance-call':'sdk-import-call',confirmed_model_request:false});
    }
    ts.forEachChild(n,walk);
  }
  walk(source);
  return out;
}
module.exports = {classify};
