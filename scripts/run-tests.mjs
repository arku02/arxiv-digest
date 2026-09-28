import { executeTests, readWorkflowConfig } from './workflow.mjs';
import { localSettings, redact } from './privacy.mjs';
const root = process.cwd();
try {
const config = readWorkflowConfig(root);
// This is a convenient test command, not a substitute for workflow verify/archive.
const result = executeTests(root, config, []);
const extra = [config.pythonExecutable, ...(localSettings(root).privateRoots ?? [])];
process.stdout.write(redact(result.output, root, extra));
if (result.error) console.error(redact(result.error, root, extra));
process.exitCode = result.passed ? 0 : 1;
} catch (error) {
  console.error(redact(error.message, root));
  process.exitCode = 1;
}
