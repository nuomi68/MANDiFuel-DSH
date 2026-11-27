/** Load the MANDiFuel protocol and prepared, offline task facts. */

import { readFileSync } from "node:fs";

export const name = "mandifuel-shell-environment";
export const inject = ["shellEnv", "systemPrompt"];

const variables = {
  DSH_MANDIFUEL_WEB_CALCULATOR: {
    description: "Web calculator creation is admitted by the per-case generation switch.",
  },
  DSH_MANDIFUEL_ENVIRONMENT_READY: {
    description: "Successful environment preparation by the MANDiFuel launcher.",
  },
  DSH_MANDIFUEL_TASK_PYTHON: {
    description: "Python 3.12 entry selected by the MANDiFuel launcher.",
  },
  DSH_MANDIFUEL_OFFBEAT_EXECUTABLE: {
    description: "OFFBEAT command selected by the launcher; preserve any budget wrapper.",
  },
  DSH_MANDIFUEL_TASK_OFFLINE: {
    description: "Task tools and subprocesses use local resources only.",
  },
};

export function apply(ctx) {
  const personaFile = new URL("./run-assistant-persona.md", import.meta.url);
  // Presets shadow the global deployment persona. Replace the assembled
  // persona slot too, so Web standard cannot restore its coding-agent identity.
  ctx.on("system-prompt/assemble", async (_assembly, context, next) => {
    const assembly = await next();
    // Preserve the assigned role of private presentation and other subagents.
    if (context?.agent?.session?.header?.origin === 'subagent') return assembly;
    // A Web host can outlive a plugin update. Read the role for the current turn.
    let persona = readFileSync(personaFile, "utf8");
    if (process.env.MANDIFUEL_WORKBENCH_BACKEND) persona += "\n网页任务的首次计算器构建由用户开启「生成计算器」触发。若对话要求首次构建，告知入口，继续完成同时提出的科学计算。已有应用可按要求演化。";
    return { ...assembly, sections: assembly.sections.map(section =>
      section.name === "deployment:persona" ? { ...section, text: persona } : section) };
  });
  const ready = process.env.MANDIFUEL_ENVIRONMENT_READY === "1";
  const runtime = ready
    ? [
        "MANDiFuel 启动器已完成环境准备：OpenFOAM 环境已加载，offbeat 和 blockMesh 已定位，Python 3.12 与内置检索索引已检查。",
        `任务 Python：${JSON.stringify(process.env.MANDIFUEL_TASK_PYTHON || "python3")}`,
        `OFFBEAT 入口：${JSON.stringify(process.env.MANDIFUEL_OFFBEAT_EXECUTABLE || "offbeat")}`,
        `插件根：${JSON.stringify(process.env.MANDIFUEL_PLUGIN_ROOT || "")}`,
        `只读算例库：${JSON.stringify(process.env.MANDIFUEL_CASE_LIBRARY_ROOT || "")}`,
        `任务可写目录：${JSON.stringify([process.env.MANDIFUEL_PROJECT_ROOT,process.env.MANDIFUEL_RUNS_ROOT].filter(Boolean))}。其余目录只读；临时文件由启动器放在项目内。权限提升不能扩大该项目边界。`,
        "任务 shell 已关闭联网；只使用准备的本地资料与软件，不用 curl、浏览器或 Python 请求绕过。需要选源时调用宿主工具 mandifuel_retrieve，仅发送选源短句。普通计算先加载所需技能，再一次读取本题相关输入、批量构建输入卡并执行公共接口。不要重复 env/which/ldd/strings、安装目录搜索、帮助查询或求解器源码巡检；也不要改用另一个二进制入口。",
        "该准备状态不代表输入和物理结果已经验证。普通运行遇到环境故障时保留日志并报告缺口，不自动检查安装或查看实现；仅用户明确指定的软件开发任务按其范围处理。",
      ].join("\n")
    : "未收到 MANDiFuel 启动器的环境就绪标记，不能宣称环境已检查。应定位会话启动准备的缺口；不要在任务内另起 DSH、遍历安装目录或读取求解器源码来猜测环境。";
  ctx.systemPrompt.section({
    name: "mandifuel:prepared-environment",
    order: 9,
    text: runtime,
  });
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
      return {
        DSH_MANDIFUEL_WEB_CALCULATOR: process.env.MANDIFUEL_WORKBENCH_BACKEND ? "switch" : "",
        DSH_MANDIFUEL_ENVIRONMENT_READY: ready ? "1" : "",
        DSH_MANDIFUEL_TASK_PYTHON: process.env.MANDIFUEL_TASK_PYTHON || "",
        DSH_MANDIFUEL_OFFBEAT_EXECUTABLE: process.env.MANDIFUEL_OFFBEAT_EXECUTABLE || "",
        DSH_MANDIFUEL_TASK_OFFLINE: "1",
      };
    },
  });
}
