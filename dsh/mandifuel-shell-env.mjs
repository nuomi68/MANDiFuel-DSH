/** Load the shared MANDiFuel protocol and forward the two RAG shell credentials. */

import { readFileSync } from "node:fs";

export const name = "mandifuel-shell-environment";
export const inject = ["shellEnv", "systemPrompt"];

const variables = {
  DSH_MANDIFUEL_MAPPING_API_KEY: {
    description: "Credential for the configured MANDiFuel RAG mapping endpoint.",
  },
  DSH_MANDIFUEL_EMBEDDING_API_KEY: {
    description: "Credential for the configured MANDiFuel RAG embedding endpoint.",
  },
};

export function apply(ctx) {
  // A separate section survives a Web preset's scoped deployment persona.
  ctx.systemPrompt.section({
    name: "mandifuel:study-protocol",
    order: 10,
    text: readFileSync(new URL("../STUDY_PROTOCOL.md", import.meta.url), "utf8"),
  });

  ctx.shellEnv.register({
    name,
    variables,
    resolve() {
      const mappingName =
        process.env.MANDIFUEL_RAG_MAPPING_API_KEY_ENV || "DEEPSEEK_API_KEY";
      const embeddingName =
        process.env.MANDIFUEL_RAG_EMBEDDING_API_KEY_ENV || "DASHSCOPE_API_KEY";
      return {
        DSH_MANDIFUEL_MAPPING_API_KEY: process.env[mappingName] || "",
        DSH_MANDIFUEL_EMBEDDING_API_KEY: process.env[embeddingName] || "",
      };
    },
  });
}
