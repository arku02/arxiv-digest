import fs from 'node:fs';
import path from 'node:path';
import {spawnSync} from 'node:child_process';
import {pathToFileURL} from 'node:url';
import {cliLocation, readWorkflowConfig, pythonCommand} from './workflow.mjs';
import {localSettings, publicValue, redact} from './privacy.mjs';

export function doctor(root) {
  root = fs.realpathSync(root);
  const result = {root, node:process.version, ready:false, issues:[]};
  const [major,minor] = process.versions.node.split('.').map(Number);
  if(major < 20 || (major === 20 && minor < 19)) result.issues.push('Node >=20.19 required');
  let config;
  try {config=readWorkflowConfig(root);result.testRunner=config.testRunner;}
  catch(e){result.issues.push(e.message);return result;}
  try {result.openspec=cliLocation(root).version;if(result.openspec!==config.openspecVersion)result.issues.push('OpenSpec version mismatch');}
  catch(e){result.issues.push(e.message);}
  result.tests=config.testFiles.map(file=>({file,exists:fs.existsSync(path.join(root,file))}));
  if(result.tests.some(t=>!t.exists))result.issues.push('Configured test files are missing');
  if(config.testRunner==='python-unittest') {
    const probe=spawnSync(pythonCommand(root,config.pythonExecutable),['-I','-B','-c',
      'import sys,json; print(json.dumps({"version":list(sys.version_info[:3]),"executable":sys.executable,"virtualenv":sys.prefix!=sys.base_prefix,"prefix":sys.prefix}))'],
      {cwd:root,encoding:'utf8',timeout:15000});
    try {
      if(probe.status!==0)throw new Error(probe.error?.message || probe.stderr || 'Python unavailable');
      result.python=JSON.parse(probe.stdout);
      if(result.python.version[0]!==3 || result.python.version[1]<10)result.issues.push('Python >=3.10 required');
    } catch(e){result.issues.push(e.message);}
  }
  result.ready=result.issues.length===0;
  result.note='Environment check only; run tests and workflow verify before delivery.';
  return result;
}
if(process.argv[1] && import.meta.url===pathToFileURL(path.resolve(process.argv[1])).href) {
  try {const result=doctor(process.cwd());console.log(JSON.stringify(publicValue(result,process.cwd(),localSettings(process.cwd()).privateRoots??[]),null,2));process.exitCode=result.ready?0:1;}
  catch(e){console.error(redact(e.message,process.cwd()));process.exitCode=1;}
}
