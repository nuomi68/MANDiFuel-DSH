/** Run case selection in the DSH host, independently of offline solver processes. */
import {execFile} from 'node:child_process';
import {copyFileSync, mkdirSync, mkdtempSync, rmSync} from 'node:fs';
import {dirname, join} from 'node:path';
import {fileURLToPath} from 'node:url';

export const name = 'mandifuel-retrieval';
export const inject = ['tools'];
const source = fileURLToPath(new URL('../rag/', import.meta.url));
const files = [
  'host_retrieval.py', 'query.py', 'providers.py', 'build_index.py',
  'data/offbeat_case_cards_compact_138.json', 'index/manifest.json', 'index/vocabulary.json',
  'index/taxonomy_index.json', 'index/description_embeddings.json',
  'experience/dual_query.py', 'experience/experience_rag.py',
  'experience/data/reviewed_corpus.json', 'experience/data/experience_index.json',
];

export function apply(ctx) {
  // Match the lifetime of the loaded plugin. Offline task tools can edit the
  // project, so never import their writable copy into a credential-bearing worker.
  const root = mkdtempSync('/tmp/mandifuel-retrieval-');
  const cleanup = () => rmSync(root, {recursive: true, force: true});
  process.once('exit', cleanup);
  ctx.on('dispose', () => {
    process.off('exit', cleanup);
    cleanup();
  });
  for (const file of files) {
    const target = join(root, 'rag', file);
    mkdirSync(dirname(target), {recursive: true});
    try {
      copyFileSync(join(source, file), target);
    } catch (error) {
      // Each retriever reports its own missing corpus or index at query time.
      if (error.code !== 'ENOENT' || !file.endsWith('.json')) throw error;
    }
  }

  const python = process.env.MANDIFUEL_TASK_PYTHON;
  const mode = process.env.MANDIFUEL_RAG_MODE || 'semantic';
  const env = {MANDIFUEL_RAG_CACHE_DIR: join(root, 'cache'), MANDIFUEL_RAG_MODE: mode};
  for (const key of ['MANDIFUEL_CASE_LIBRARY_ROOT', 'MANDIFUEL_RAG_TIMEOUT_SECONDS',
    'HTTPS_PROXY', 'HTTP_PROXY', 'NO_PROXY', 'https_proxy', 'http_proxy', 'no_proxy', 'SSL_CERT_FILE', 'SSL_CERT_DIR']) {
    if (process.env[key]) env[key] = process.env[key];
  }
  for (const [role, defaultKey] of [['MAPPING', 'DEEPSEEK_API_KEY'], ['EMBEDDING', 'DASHSCOPE_API_KEY']]) {
    const prefix = 'MANDIFUEL_RAG_' + role + '_';
    for (const suffix of ['MODEL', 'BASE_URL', 'DIMENSION']) {
      if (process.env[prefix + suffix]) env[prefix + suffix] = process.env[prefix + suffix];
    }
    const key = process.env[prefix + 'API_KEY_ENV'] || defaultKey;
    if (mode === 'semantic' && process.env[key]) env[defaultKey] = process.env[key];
  }

  const parameters = {
    query: {type: 'string', required: true, maxLength: 1200, description: '选源短句，概括物理对象、几何、载荷和所求量。'},
    purpose: {type: 'string', enum: ['solve', 'troubleshoot']},
    case_limit: {type: 'integer', minimum: 1, maximum: 10},
    experience_limit: {type: 'integer', minimum: 1, maximum: 10},
    arm: {type: 'string', enum: ['bare', 'skill']},
    source_run: {type: 'string', maxLength: 100},
    task_status: {type: 'string', enum: ['completed', 'prepared', 'incomplete']},
    review_status: {type: 'string', enum: ['all', 'pass', 'troubleshooting_only']},
    include_case_examples: {type: 'boolean'},
  };
  if (mode === 'local') {
    parameters.labels_json = {type: 'string', description: '本地词表中明确适用的九分面标签，JSON 对象。'};
  }
  ctx.tools.register({
    name: 'mandifuel_retrieve',
    description: '检索 OFFBEAT 算例卡和审核经验，分别返回候选、依据和来源。' +
      (mode === 'local' ? '当前为离线 BM25 模式，请提供英文工程关键词和适用标签。' : '当前为语义融合模式，自动映射九分面并匹配描述向量。'),
    parameters,
    output: {schema: {type: 'object'}, render: (_args, result) => [{type: 'text', text: JSON.stringify(result)}]},
    execute(args, exec) {
      return new Promise((resolve, reject) => {
        const child = execFile(python, ['-I', '-B', join(root, 'rag', 'host_retrieval.py')], {
          cwd: root, env, signal: exec.signal, maxBuffer: 4 * 1024 * 1024,
          timeout: 2 * Number(env.MANDIFUEL_RAG_TIMEOUT_SECONDS || 120) * 1000 + 10000,
        }, (error, stdout) => {
          if (error) return reject(new Error('检索宿主中断、超时或运行失败'));
          try { resolve(JSON.parse(stdout)); }
          catch { reject(new Error('检索宿主返回无效 JSON')); }
        });
        child.stdin.on('error', () => {}); // execFile reports early exit and abort.
        child.stdin.end(JSON.stringify(args));
      });
    },
  });
}
