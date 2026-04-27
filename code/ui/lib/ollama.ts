export const OLLAMA_HOST = process.env.OLLAMA_HOST ?? "http://localhost:11434";
export const DEFAULT_MODEL = process.env.OLLAMA_DEFAULT_MODEL ?? "gpt-oss:120b";
export const ROUTER_MODEL = process.env.OLLAMA_ROUTER_MODEL ?? DEFAULT_MODEL;
