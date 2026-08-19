import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { OutputRecord, TaskRecord } from "../../types";

afterEach(cleanup);
import { ModuleActivityOutputRow, ModuleActivityTaskRow, ModuleOutputPlayer, ModuleStatusHeader } from "./ModuleWorkbenchShell";

const output: OutputRecord = {
  id: "output-1", task_id: "task-1", filename: "测试音频.wav", created_at: "2026-08-13T10:00:00",
  duration: 3, sample_rate: 48000, channels: 2, bit_depth: 24, format: "WAV", voice: "无参考音色",
  text: "测试", artifact_url: "/api/v2/artifacts/output-1", module: "speech", kind: "speech_output",
};
const task: TaskRecord = {
  id: "task-1", project_id: "project-1", module: "speech", status: "running", progress: .4,
  message: "正在生成", created_at: "2026-08-13T10:00:00", updated_at: "2026-08-13T10:00:01",
  result_id: null, error: null, remove_after_stop: false,
};

describe("shared module workbench components", () => {
  it("renders a module-aware status header and current output", () => {
    render(<><ModuleStatusHeader module="speech" title="模块已安装" detail="运行环境已检测" /><ModuleOutputPlayer module="speech" output={output} emptyDetail="暂无" /></>);
    expect(screen.getByText("MODULE STATUS")).toBeInTheDocument();
    expect(screen.getByText("测试音频.wav")).toBeInTheDocument();
    expect(screen.getByText(/48 kHz/)).toBeInTheDocument();
  });

  it("routes task and output row actions", () => {
    const cancel = vi.fn(); const remove = vi.fn(); const select = vi.fn();
    render(<><ModuleActivityTaskRow task={task} onCancel={cancel} onRemove={remove} /><ModuleActivityOutputRow module="speech" output={output} onSelect={select} /></>);
    fireEvent.click(screen.getByText("安全停止"));
    fireEvent.click(screen.getByLabelText("移除此任务"));
    fireEvent.click(screen.getAllByText("测试音频.wav").at(-1)!);
    expect(cancel).toHaveBeenCalledWith(task);
    expect(remove).toHaveBeenCalledWith(task);
    expect(select).toHaveBeenCalledWith(output);
  });

  it("uses the module-specific empty output copy", () => {
    render(<ModuleOutputPlayer module="sound_effect" output={null} emptyDetail="生成后显示" />);
    expect(screen.getByText("还没有音效输出")).toBeInTheDocument();
  });
});


describe("ModuleOutputPlayer download", () => {
  it("uses the controlled save flow and reports success", async () => {
    const native = await import("../../services/native");
    const save = vi.spyOn(native, "saveArtifact").mockResolvedValue({ status: "saved", filename: output.filename });
    const onMessage = vi.fn();
    render(<ModuleOutputPlayer module="speech" output={output} emptyDetail="暂无" onMessage={onMessage} />);
    fireEvent.click(screen.getByRole("button", { name: "下载" }));
    await waitFor(() => expect(save).toHaveBeenCalledWith("output-1", "测试音频.wav"));
    expect(onMessage).toHaveBeenCalledWith("文件已保存。", "success");
    save.mockRestore();
  });
});
