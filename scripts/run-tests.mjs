import fs from 'node:fs';
import { executeTests } from './workflow.mjs';
const root = process.cwd();
const config = JSON.parse(fs.readFileSync('workflow.config.json', 'utf8'));
// This is a convenient test command, not a substitute for workflow verify/archive.
const result = executeTests(root, config, []);
process.stdout.write(result.output);
if (result.error) console.error(result.error);
process.exitCode = result.passed ? 0 : 1;
