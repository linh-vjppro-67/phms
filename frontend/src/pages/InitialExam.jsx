// M03 – Khám ban đầu (WF-01 bước 4–7): danh sách chờ → wizard khám.
import { useState } from "react";
import { api, idem } from "../api";
import Workbench from "../components/Workbench.jsx";
import { Badge, Card, DataTable, Empty, PageHeader, Seg, fmtDate, useAct, useAuth, useLoad } from "../ui.jsx";

export default function InitialExam() {
  const { refreshStats } = useAuth();
  const act = useAct();
  const [view, setView] = useState("waiting");
  const [open, setOpen] = useState(null);
  const recv = useLoad(() => api("GET", "/stays?status=received"), []);
  const done = useLoad(() => api("GET", "/stays?status=managed"), [], view !== "done");
  const reload = () => { recv.reload(); done.reload(); refreshStats(); };

  const start = async (s) => {
    const e = await act(() => api("POST", "/encounters", { person_id: s.person_id, type: "initial", reason: "Khám sức khỏe ban đầu khi tiếp nhận" }, idem()));
    if (!e?.id) return;
    await act(() => api("POST", `/encounters/${e.id}/transition`, { to: "in_progress" }));
    reload(); setOpen(e.id);
  };
  if (open) return (
    <>
      <PageHeader title="Khám ban đầu" sub="Thực hiện lần lượt từng bước; có thể quay lại bất kỳ lúc nào." actions={<button className="btn" onClick={() => { setOpen(null); reload(); }}>← Danh sách chờ khám</button>} />
      <Workbench id={open} wizard onChanged={reload} />
    </>
  );
  const waiting = (recv.data || []).filter((s) => !s.initial_encounter_id);
  const going = (recv.data || []).filter((s) => s.initial_encounter_id);
  const rows = { waiting, going, done: done.data }[view];
  return (
    <>
      <PageHeader title="Khám ban đầu" sub="M03 · Mọi người mới tiếp nhận cần được đánh giá sức khỏe ban đầu; kết quả hình thành hồ sơ sức khỏe và lịch theo dõi." />
      <div style={{ marginBottom: 14 }}><Seg value={view} onChange={setView} items={[{ id: "waiting", label: `Chờ khám (${waiting.length})` }, { id: "going", label: `Đang khám dở (${going.length})` }, { id: "done", label: "Đã hoàn tất" }]} /></div>
      <Card flat>
        <DataTable rows={rows} loading={recv.loading} empty={<Empty title={view === "waiting" ? "Không có ai đang chờ khám ban đầu" : "Không có dữ liệu"} />}
          columns={[{ h: "Họ tên", c: (s) => <b>{s.person_name}</b> }, { h: "Mã nguồn", c: (s) => s.person_external_id || <Badge tone="warn">Chưa có mã</Badge> }, { h: "Tiếp nhận", c: (s) => fmtDate(s.start_date) },
            view === "going" && { h: "Trạng thái khám", c: (s) => <Badge tone="info">{s.initial_encounter_status === "draft" ? "Nháp" : "Đang khám"}</Badge> },
            view === "done" && { h: "Hoàn tất lúc", c: (s) => fmtDate(s.initial_exam_completed_at) },
            { h: "", cls: "r", c: (s) => view === "waiting" ? <button className="btn sm primary" onClick={() => start(s)}>Bắt đầu khám</button>
              : <button className="btn sm" onClick={() => setOpen(s.initial_encounter_id)}>{view === "going" ? "Tiếp tục" : "Xem"}</button> }].filter(Boolean)} />
      </Card>
    </>
  );
}
