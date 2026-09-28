import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { createHash } from 'node:crypto';
import { spawnSync } from 'node:child_process';
import { pathToFileURL } from 'node:url';

const hash = data => createHash('sha256').update(data).digest('hex');
const fail = message => { throw new Error(message); };
const localName = 'workflow.local.json';
const allowName = 'privacy-allowlist.json';
const maxBytes = 8 * 1024 * 1024;
const marker = '# integrated-workflow-privacy-v1';
const escape = value => value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');

export function localSettings(root) {
  const file = path.join(root, localName);
  if (!fs.existsSync(file)) return {};
  if (fs.lstatSync(file).isSymbolicLink()) fail('Local workflow settings must not be a symbolic link');
  let value;
  try { value = JSON.parse(fs.readFileSync(file, 'utf8')); }
  catch { fail('Invalid workflow.local.json; expected JSON'); }
  if (!value || Array.isArray(value) || typeof value !== 'object'
      || Object.keys(value).some(key => !['pythonExecutable', 'privateRoots'].includes(key))
      || (value.pythonExecutable !== undefined && (typeof value.pythonExecutable !== 'string' || !value.pythonExecutable.trim()))
      || (value.privateRoots !== undefined && (!Array.isArray(value.privateRoots)
        || value.privateRoots.some(item => typeof item !== 'string' || !path.isAbsolute(item) || item === path.parse(item).root)))) {
    fail('Invalid workflow.local.json; only pythonExecutable and absolute privateRoots are supported');
  }
  return value;
}

// Work on output copies only. This function never changes argv, source files or config.
export function redact(text, root, extra = []) {
  const mappings = [[path.resolve(root), '<PROJECT_ROOT>'], [os.homedir(), '<HOME>'],
    [process.execPath, '<NODE_EXECUTABLE>'], ...extra.filter(Boolean).map(item => [item, '<LOCAL_PATH>'])]
    .filter(([item]) => typeof item === 'string' && (path.isAbsolute(item) || /^[a-z]:[\\/]/i.test(item)))
    .sort((a, b) => b[0].length - a[0].length);
  let result = String(text);
  for (const [original, replacement] of mappings) {
    const slash = original.replaceAll('\\', '/').replace(/\/$/, '');
    const variants = new Set([original, slash, slash.replaceAll('/', '\\'),
      slash.replaceAll('/', '\\\\'), encodeURI(slash), encodeURIComponent(original), encodeURIComponent(slash)]);
    if (/^[a-z]:\//i.test(slash)) variants.add('file:///' + encodeURI(slash));
    else if (slash.startsWith('/')) variants.add('file://' + encodeURI(slash));
    for (const variant of [...variants].sort((a, b) => b.length - a.length)) {
      result = result.replace(new RegExp(escape(variant) + '(?=$|[\\\\/\\s"\'<>),;:%])', /^[a-z]:/i.test(slash) ? 'gi' : 'g'), replacement);
    }
  }
  // Other users' home paths and drive/UNC paths may appear in copied diagnostics.
  return result
    .replace(/(?:file:\/{2,3})?(?<![a-z0-9])[a-z]:[\\/]+[^\s"'<>|\r\n)\]}]+/gi, '<ABSOLUTE_PATH>')
    .replace(/(?:file:\/\/)?\/(?:Users|home)\/[^\s/"'<>]+/g, '<HOME>')
    .replace(/\/root(?=\/|[\s"']|$)/g, '<HOME>')
    .replace(/\\\\[^\s\\/"'<>]+[\\/]+[^\s"'<>]+/g, '<NETWORK_PATH>');
}

export function publicValue(value, root, extra = []) {
  // Preserve types and JSON syntax even when a path occurs in an object key.
  if (typeof value === 'string') return redact(value, root, extra);
  if (Array.isArray(value)) return value.map(item => publicValue(item, root, extra));
  if (value && typeof value === 'object') return Object.fromEntries(Object.entries(value)
    .map(([key, item]) => [redact(key, root, extra), publicValue(item, root, extra)]));
  return value;
}

function decoded(text) {
  return text.replace(/\\u([0-9a-f]{4})/gi, (_, hex) => String.fromCharCode(parseInt(hex, 16)))
    .replace(/\\\//g, '/').replace(/(?:%[0-9a-f]{2})+/gi, block => {
      try { return decodeURIComponent(block); }
      catch { return block.replace(/%([0-9a-f]{2})/gi, (_, hex) => String.fromCharCode(parseInt(hex, 16))); }
    })
    .replace(/\\+/g, '/');
}

export function pathIssues(text, root, extra = []) {
  const content = decoded(String(text));
  const known = [root, os.homedir(), process.execPath, process.env.WORKFLOW_PYTHON, ...extra]
    .filter(item => typeof item === 'string' && (path.isAbsolute(item) || /^[a-z]:[\\/]/i.test(item)))
    .map(item => decoded(item)).filter(item => item.length > 3);
  const reasons = [];
  if (known.some(item => new RegExp(escape(item) + '(?=$|[/\\s"\'<>),;:])', 'i').test(content))) reasons.push('local-path');
  if (/(?<![a-z0-9])[a-z]:\//i.test(content)) reasons.push('drive-path');
  if (/\/(?:Users|home)\/[^\s/"'<>]+|\/root(?:\/|[\s"']|$)/.test(content)) reasons.push('home-path');
  if (/(?:^|[\s"'=])\/\/[\p{L}\p{N}][\p{L}\p{N}._-]*\/[^\s/]+/u.test(content)) reasons.push('network-path');
  return [...new Set(reasons)];
}

function git(root, args, input, binary = false) {
  const result = spawnSync('git', ['--no-replace-objects', ...args], { cwd: root,
    env: { ...process.env, GIT_NO_REPLACE_OBJECTS: '1', GIT_OPTIONAL_LOCKS: '0' },
    input, encoding: binary ? undefined : 'utf8', timeout: 60000, maxBuffer: 64 * 1024 * 1024 });
  if (result.error || result.status !== 0) fail('Git privacy check could not finish (' + args[0] + '); operation blocked');
  return result.stdout;
}

function repository(root) {
  if (git(root, ['rev-parse', '--is-inside-work-tree']).trim() !== 'true') fail('Run inside a Git working tree');
  return fs.realpathSync(git(root, ['rev-parse', '--show-toplevel']).trim());
}

function privateFile(name) {
  return /(^|\/)(workflow\.local\.json|\.env(?:\..*)?|config\.ini)(?:$|\/)/i.test(name) && !/(^|\/)\.env\.example$/i.test(name)
    || /(^|\/)\.workflow\/(?:private|imports)(?:\/|$)/i.test(name)
    || /(^|\/)\.workflow\/python-[^/]+\.json$/i.test(name);
}

function allowances(text) {
  if (!text) return [];
  let value;
  try { value = JSON.parse(text); } catch { fail('Invalid privacy-allowlist.json'); }
  if (!Array.isArray(value) || value.some(item => !item || typeof item.file !== 'string'
      || item.file.startsWith('/') || item.file.includes('..') || item.file.includes('\\')
      || !/^[a-f0-9]{64}$/.test(item.sha256 ?? '') || typeof item.reason !== 'string' || !item.reason.trim())) {
    fail('Allowlist entries require a relative file, exact sha256 and nonempty reason');
  }
  return value;
}

function readObjects(root, ids, inspect) {
  const unique = [...new Set(ids)];
  if (unique.length > 50000) fail('History exceeds 50000 objects; arrange a separate review before upload');
  for (let start = 0; start < unique.length; start += 4) {
    const chunk = unique.slice(start, start + 4);
    const sizes = git(root, ['cat-file', '--batch-check'], chunk.join('\n') + '\n').trim().split('\n');
    if (sizes.some(line => !/^[a-f0-9]+ (blob|tree|commit|tag) \d+$/.test(line) || Number(line.split(' ')[2]) > maxBytes)) {
      fail('Missing or oversized Git object; operation blocked (limit: 8 MiB per object)');
    }
    const data = git(root, ['cat-file', '--batch'], chunk.join('\n') + '\n', true);
    let offset = 0;
    for (const id of chunk) {
      const end = data.indexOf(10, offset);
      const [actual, type, length] = data.subarray(offset, end).toString('utf8').split(' ');
      const size = Number(length);
      if (actual !== id || !Number.isSafeInteger(size) || size < 0 || end + size + 1 >= data.length) fail('Incomplete Git object scan');
      inspect(id, type, data.subarray(end + 1, end + 1 + size));
      offset = end + size + 2;
    }
  }
}

function inspectContent(data) {
  if (data.includes(0)) return null;
  try { return new TextDecoder('utf-8', { fatal: true }).decode(data); } catch { return null; }
}

export function scan(root, mode = 'staged', tips) {
  root = repository(root);
  const settings = localSettings(root);
  const extra = [settings.pythonExecutable, ...(settings.privateRoots ?? [])].filter(Boolean);
  const entries = new Map();
  let allowText = '';
  const add = (id, file) => entries.set(id, [...(entries.get(id) ?? []), file]);
  if (mode === 'staged') {
    for (const record of git(root, ['ls-files', '--stage', '-z']).split('\0').filter(Boolean)) {
      const match = /^(\d+) ([a-f0-9]+) (\d)\t([\s\S]*)$/.exec(record);
      if (!match || match[3] !== '0') fail('Unmerged index; resolve before committing');
      if (match[1] === '160000') fail('Submodule content requires separate privacy review');
      add(match[2], match[4]);
    }
    for (const [id, names] of entries) if (names.includes(allowName)) allowText = git(root, ['cat-file', 'blob', id]);
  } else if (mode === 'history') {
    if (git(root, ['rev-parse', '--is-shallow-repository']).trim() === 'true') fail('Shallow history cannot be fully checked; operation blocked');
    const grafts = git(root, ['rev-parse', '--git-path', 'info/grafts']).trim();
    if (fs.existsSync(path.resolve(root, grafts))) fail('Grafted history cannot be fully checked');
    if (tips && tips.some(id => !/^(?:[a-f0-9]{40}|[a-f0-9]{64})$/.test(id))) fail('Invalid push object ID');
    const listing = tips
      ? (tips.length ? git(root, ['rev-list', '--objects', '--no-object-names', '--stdin'], tips.join('\n') + '\n') : '')
      : git(root, ['rev-list', '--objects', '--no-object-names', '--all']);
    for (const line of listing.split('\n').filter(Boolean)) {
      const space = line.indexOf(' '), id = space < 0 ? line : line.slice(0, space);
      add(id, space < 0 ? '' : line.slice(space + 1));
    }
    // Local, explicit exceptions remain bound to the exact file bytes, never a glob.
    const allowFile = path.join(root, allowName);
    if (fs.existsSync(allowFile)) allowText = fs.readFileSync(allowFile, 'utf8');
  } else fail('Use staged or history');
  const allowed = allowances(allowText);
  const findings = [];
  const report = (file, id, reason) => findings.push({ file: redact(file || '(commit/tag metadata)', root, extra), object: id.slice(0, 12), reason });
  const facts = new Map(), trees = new Map(), treeRoots = new Set();
  readObjects(root, [...entries.keys()], (id, type, data) => {
    if (type === 'tree') {
      // Parse raw tree entries: filenames may contain whitespace, newlines or backslashes.
      const children = []; let offset = 0;
      while (offset < data.length) {
        const space = data.indexOf(32, offset), zero = data.indexOf(0, space);
        const bytes = id.length / 2;
        if (space < 0 || zero < 0 || zero + 1 + bytes > data.length) fail('Invalid Git tree');
        const name = inspectContent(data.subarray(space + 1, zero));
        if (name === null) fail('Non-UTF8 filename requires separate privacy review');
        children.push({ mode: data.subarray(offset, space).toString(), name,
          id: data.subarray(zero + 1, zero + 1 + bytes).toString('hex') });
        offset = zero + 1 + bytes;
      }
      trees.set(id, children); return;
    }
    const text = inspectContent(data);
    if (type === 'commit') {
      const tree = /^tree ([a-f0-9]+)\n/.exec(text ?? '')?.[1];
      if (!tree) fail('Cannot read commit tree');
      treeRoots.add(tree);
    }
    if (type === 'tag' && /^type tree$/m.test(text ?? '')) {
      const tree = /^object ([a-f0-9]+)\n/.exec(text ?? '')?.[1];
      if (tree) treeRoots.add(tree);
    }
    const reasons = text === null ? ['binary-or-non-UTF8-needs-review'] : pathIssues(text, root, extra);
    if (text?.startsWith('version https://git-lfs.github.com/spec/v1')) reasons.push('LFS-content-needs-separate-review');
    facts.set(id, { type, reasons, digest: hash(data) });
  });
  if (mode === 'history') {
    // Every tree at every historical path matters, even when a blob is reused under another name.
    const visited = new Set();
    const walkTree = (id, prefix = '') => {
      const key = id + ':' + prefix;
      if (visited.has(key)) return;
      visited.add(key);
      if (visited.size > 100000 || prefix.length > 4096) fail('History path traversal limit exceeded');
      const children = trees.get(id);
      if (!children) fail('Missing historical tree');
      for (const child of children) {
        const file = prefix + child.name;
        if (child.mode === '160000') fail('Submodule content requires separate privacy review');
        add(child.id, file);
        if (child.mode === '40000') walkTree(child.id, file + '/');
      }
    };
    for (const tree of treeRoots) walkTree(tree);
  }
  for (const [id, originalNames] of entries) {
    const names = [...new Set(originalNames.filter(Boolean))];
    if (!names.length) names.push('');
    const fact = facts.get(id);
    for (const file of names) {
      if (privateFile(file)) report(file, id, 'private-file-must-stay-local');
      for (const reason of pathIssues(file, root, extra)) report(file, id, 'filename-' + reason);
      if (!fact) continue;
      if (fact.type === 'blob' && !privateFile(file) && !fact.reasons.includes('LFS-content-needs-separate-review')
          && allowed.some(item => item.file === file && item.sha256 === fact.digest)) continue;
      for (const reason of fact.reasons) report(file, id, reason);
    }
  }
  return { mode, passed: findings.length === 0, objects: entries.size, findings };
}

function hookContents(relative) {
  const prefix = '#!/bin/sh\n' + marker + '\n';
  return {
    'pre-commit': prefix + 'exec node "' + relative + '" staged\n',
    'commit-msg': prefix + 'exec node "' + relative + '" message "$1"\n',
    'pre-push': prefix + 'exec node "' + relative + '" pre-push\n',
  };
}

export function installHooks(root) {
  root = repository(root);
  const current = spawnSync('git', ['config', '--get', 'core.hooksPath'], { cwd: root, encoding: 'utf8' });
  if (current.error || ![0, 1].includes(current.status)) fail('Cannot inspect existing hooks configuration');
  if (current.status === 0) fail('Existing core.hooksPath detected; integrate privacy commands with those hooks manually');
  const relative = fs.existsSync(path.join(root, '.integration/scripts/privacy.mjs')) ? '.integration/scripts/privacy.mjs' : 'scripts/privacy.mjs';
  if (!fs.existsSync(path.join(root, relative))) fail('Privacy script must be installed in this project first');
  const directory = path.resolve(root, git(root, ['rev-parse', '--git-path', 'hooks']).trim());
  if (fs.existsSync(directory) && fs.lstatSync(directory).isSymbolicLink()) fail('Linked hooks directory is unsupported');
  const hooks = hookContents(relative);
  // Preflight all files before writing any, preserving existing hook tools.
  for (const [name, content] of Object.entries(hooks)) {
    const target = path.join(directory, name);
    if (fs.existsSync(target) && (fs.lstatSync(target).isSymbolicLink() || fs.readFileSync(target, 'utf8') !== content)) {
      fail('Existing ' + name + ' hook detected; integrate manually, no hooks changed');
    }
  }
  fs.mkdirSync(directory, { recursive: true });
  for (const [name, content] of Object.entries(hooks)) {
    fs.writeFileSync(path.join(directory, name), content, { mode: 0o755 });
    fs.chmodSync(path.join(directory, name), 0o755);
  }
  return { installed: true, hooks: Object.keys(hooks), note: 'Local hooks installed. History is checked again on each push. Install on every clone.' };
}

export function pushTips(input) {
  return input.split(/\r?\n/).filter(Boolean).flatMap(line => {
    const fields = line.trim().split(/\s+/);
    if (fields.length !== 4 || !/^(?:[a-f0-9]{40}|[a-f0-9]{64})$/.test(fields[1])) fail('Invalid pre-push input');
    return /^0+$/.test(fields[1]) ? [] : [fields[1]];
  });
}

if (process.argv[1] && import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href) {
  try {
    const root = process.cwd(), action = process.argv[2];
    let result;
    if (action === 'install') result = installHooks(root);
    else if (action === 'staged' || action === 'history') result = scan(root, action);
    else if (action === 'pre-push') result = scan(root, 'history', pushTips(fs.readFileSync(0, 'utf8')));
    else if (action === 'message') {
      const settings = localSettings(root);
      const reasons = pathIssues(fs.readFileSync(process.argv[3], 'utf8'), root, settings.privateRoots ?? []);
      result = { passed: reasons.length === 0, reasons };
    } else fail('Use privacy.mjs install | staged | history');
    console.log(JSON.stringify(result, null, 2));
    if (result.passed === false) process.exitCode = 1;
  } catch (error) {
    // Error text from IO may itself contain a private path.
    console.error(redact(error.message, process.cwd()));
    process.exitCode = 1;
  }
}
