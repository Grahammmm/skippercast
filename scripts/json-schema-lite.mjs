// A small JSON Schema (draft 2020-12) checker for the repository's own schemas, so the client build can hold a
// file to the exact contract in catalog/relief/pointer.schema.json without a new dependency.
//
// It supports only the keywords those schemas use. A keyword it does not know THROWS instead of being skipped:
// a new constraint added to a schema must never be silently unenforced at publication time.
const ANNOTATIONS = new Set(['$schema', '$defs', 'title', 'description']);
const KEYWORDS = new Set([
  '$ref', 'allOf', 'anyOf', 'oneOf', 'type', 'const', 'enum', 'required', 'properties', 'patternProperties',
  'additionalProperties', 'unevaluatedProperties', 'minProperties', 'prefixItems', 'items', 'minItems', 'maxItems',
  'minLength', 'maxLength', 'pattern', 'minimum', 'maximum', 'exclusiveMinimum',
]);

const kind = value => value === null ? 'null' : Array.isArray(value) ? 'array' : Number.isInteger(value) ? 'integer' : typeof value;
const isType = (value, type) => type === 'number' ? typeof value === 'number' && Number.isFinite(value) : kind(value) === type;
const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);   // const/enum values here are scalars

/**
 * Check `value` against `schema` (the whole document, so `#/$defs/...` references resolve).
 * Returns a list of "path: problem" strings; empty means valid.
 */
export function validateSchema(value, schema) {
  const errors = [];
  const resolve = ref => {
    if (!ref.startsWith('#/')) throw Error(`json-schema-lite: unsupported $ref ${ref}`);
    let node = schema;
    for (const part of ref.slice(2).split('/')) node = node?.[part.replaceAll('~1', '/').replaceAll('~0', '~')];
    if (node === undefined) throw Error(`json-schema-lite: unresolved $ref ${ref}`);
    return node;
  };
  // Returns the property names this schema evaluated (for unevaluatedProperties); pushes into `out` on failure.
  const check = (node, data, path, out) => {
    if (node === true) return new Set();
    if (node === false) { out.push(`${path}: not allowed`); return new Set(); }
    for (const key of Object.keys(node)) {
      if (!KEYWORDS.has(key) && !ANNOTATIONS.has(key)) throw Error(`json-schema-lite: unsupported keyword ${key}`);
    }
    const evaluated = new Set();
    const fail = message => out.push(`${path || '/'}: ${message}`);
    const sub = (child, data2, path2) => check(child, data2, path2, out);
    const probe = (child, data2) => { const trial = []; const names = check(child, data2, path, trial); return {ok: trial.length === 0, names}; };

    if (node.$ref) for (const name of sub(resolve(node.$ref), data, path)) evaluated.add(name);
    for (const part of node.allOf ?? []) for (const name of sub(part, data, path)) evaluated.add(name);
    if (node.anyOf) {
      const hits = node.anyOf.map(part => probe(part, data)).filter(result => result.ok);
      if (!hits.length) fail('matches none of the allowed forms');
      for (const hit of hits) for (const name of hit.names) evaluated.add(name);
    }
    if (node.oneOf) {
      const hits = node.oneOf.map(part => probe(part, data)).filter(result => result.ok);
      if (hits.length !== 1) fail(`must match exactly one allowed form, matches ${hits.length}`);
      for (const hit of hits) for (const name of hit.names) evaluated.add(name);
    }

    if ('const' in node && !same(data, node.const)) fail(`must be ${JSON.stringify(node.const)}`);
    if (node.enum && !node.enum.some(option => same(data, option))) fail(`must be one of ${JSON.stringify(node.enum)}`);
    if (node.type && !isType(data, node.type)) { fail(`must be ${node.type}`); return evaluated; }

    if (typeof data === 'string') {
      if (node.minLength !== undefined && data.length < node.minLength) fail(`shorter than ${node.minLength}`);
      if (node.maxLength !== undefined && data.length > node.maxLength) fail(`longer than ${node.maxLength}`);
      if (node.pattern !== undefined && !new RegExp(node.pattern, 'u').test(data)) fail(`does not match ${node.pattern}`);
    }
    if (typeof data === 'number') {
      if (node.minimum !== undefined && data < node.minimum) fail(`below ${node.minimum}`);
      if (node.maximum !== undefined && data > node.maximum) fail(`above ${node.maximum}`);
      if (node.exclusiveMinimum !== undefined && data <= node.exclusiveMinimum) fail(`not above ${node.exclusiveMinimum}`);
    }
    if (Array.isArray(data)) {
      if (node.minItems !== undefined && data.length < node.minItems) fail(`fewer than ${node.minItems} items`);
      if (node.maxItems !== undefined && data.length > node.maxItems) fail(`more than ${node.maxItems} items`);
      const prefix = node.prefixItems ?? [];
      prefix.forEach((child, index) => { if (index < data.length) sub(child, data[index], `${path}/${index}`); });
      if (node.items !== undefined) data.slice(prefix.length).forEach((item, index) => sub(node.items, item, `${path}/${prefix.length + index}`));
    }
    if (kind(data) === 'object') {
      const names = Object.keys(data);
      if (node.minProperties !== undefined && names.length < node.minProperties) fail(`fewer than ${node.minProperties} properties`);
      for (const name of node.required ?? []) if (!Object.hasOwn(data, name)) fail(`missing required ${name}`);
      for (const [name, child] of Object.entries(node.properties ?? {})) {
        if (Object.hasOwn(data, name)) { evaluated.add(name); sub(child, data[name], `${path}/${name}`); }
      }
      const patterns = Object.entries(node.patternProperties ?? {}).map(([source, child]) => [new RegExp(source, 'u'), child]);
      for (const name of names) {
        let matched = false;
        for (const [pattern, child] of patterns) if (pattern.test(name)) { matched = true; evaluated.add(name); sub(child, data[name], `${path}/${name}`); }
        if (node.additionalProperties !== undefined && !matched && !Object.hasOwn(node.properties ?? {}, name)) {
          evaluated.add(name);
          if (node.additionalProperties === false) fail(`unexpected property ${name}`);
          else sub(node.additionalProperties, data[name], `${path}/${name}`);
        }
      }
      if (node.unevaluatedProperties !== undefined) {
        for (const name of names) {
          if (evaluated.has(name)) continue;
          evaluated.add(name);
          if (node.unevaluatedProperties === false) fail(`unexpected property ${name}`);
          else sub(node.unevaluatedProperties, data[name], `${path}/${name}`);
        }
      }
    }
    return evaluated;
  };
  check(schema, value, '', errors);
  return errors;
}
