import { api } from "../api";
import { ROLE_LABEL } from "../labels";
import { Badge, Card, Icon, DataTable, Empty, PageHeader, Status, fmtDate, fmtDT, useAuth, useLoad } from "../ui.jsx";

const TILES = [
  ["open_emergencies", "alert", "Sự kiện cấp cứu đang mở", "emergency", "bad"], ["new_alerts", "bell", "Cảnh báo mới", "chronic", "bad"],
  ["overdue_appointments", "calendar", "Lịch quá hạn", "chronic", "bad"], ["awaiting_initial_exam", "clip", "Chờ khám ban đầu", "initial", "warn"],
  ["pending_verification", "users", "Hồ sơ chờ đối soát danh tính", "intake", "warn"], ["orders_draft", "file", "Đơn thuốc chờ xác nhận", "rx", "warn"],
  ["dispense_queue", "pill", "Đơn chờ cấp phát", "pharmacy", "warn"], ["referrals_post_review", "truck", "Chuyển viện cần hậu kiểm", "referral", "warn"],
  ["pending_handovers", "swap", "Bàn giao chờ xác nhận", "handover", "warn"], ["open_encounters", "activity", "Lượt khám đang mở", "exam", ""],
  ["awaiting_results", "activity", "Lượt khám chờ kết quả", "exam", ""], ["appointments_today", "calendar", "Lịch hẹn hôm nay", "periodic", ""],
  ["open_referrals", "truck", "Chuyển viện đang mở", "referral", ""], ["active_persons", "users", "Đang được quản lý", "intake", "ok"],
];

export default function Dashboard() {
  const { user, has, stats, go } = useAuth();
  const { data: facs } = useLoad(() => api("GET", "/facilities"), []);
  const fac = facs?.find((f) => f.id === user.facility_id);
  const { data: overdue } = useLoad(() => api("GET", "/appointments?overdue=true&limit=8"), [], !has("schedule.read"));
  const { data: alerts } = useLoad(() => api("GET", "/alerts?status=new"), [], !has("schedule.read"));
  const { data: waiting } = useLoad(() => api("GET", "/stays?status=received"), [], !(has("person.read") && has("encounter.write")));
  const tiles = TILES.filter(([k]) => k in stats);

  return (
    <>
      <PageHeader title={`Xin chào, ${user.full_name}`} sub={`${ROLE_LABEL[user.role] || user.role}${fac ? ` · ${fac.name}` : ""}`} />
      {user.role === "sysadmin" && <Card><Empty title="Tài khoản quản trị không xem dữ liệu bệnh án">Dùng mục “Quản trị hệ thống” để quản lý người dùng, phân quyền, danh mục và nhật ký kiểm toán.</Empty></Card>}
      {tiles.length > 0 && (
        <div className="kpis">
          {tiles.map(([k, ic, label, to, tone]) => (
            <button key={k} className={`kpi ${stats[k] > 0 ? tone : ""}`} onClick={() => go(to)}><span className="kicon"><Icon n={ic} size={18} /></span><b>{stats[k]}</b><span>{label}</span></button>
          ))}
        </div>
      )}
      <div className="cols">
        {has("schedule.read") && (
          <Card title="Cảnh báo mới" actions={<button className="btn sm" onClick={() => go("chronic")}>Xem tất cả</button>} flat>
            <DataTable rows={alerts?.slice(0, 6)} empty={<Empty title="Không có cảnh báo mới" />}
              columns={[{ h: "Thời điểm", c: (a) => fmtDT(a.created_at) }, { h: "Nội dung", c: (a) => a.message }, { h: "Mức", c: (a) => (a.level ? <Badge tone="bad">Nâng mức {a.level}</Badge> : "—") }]} onRow={() => go("chronic")} />
          </Card>
        )}
        {has("schedule.read") && (
          <Card title="Lịch hẹn quá hạn" actions={<button className="btn sm" onClick={() => go("periodic")}>Khám định kỳ</button>} flat>
            <DataTable rows={overdue} empty={<Empty title="Không có lịch quá hạn" />}
              columns={[{ h: "Hạn", c: (a) => fmtDate(a.due_date) }, { h: "Người", c: (a) => a.person_name || a.person_id.slice(0, 8) }, { h: "Loại", c: (a) => (a.kind === "periodic" ? "Định kỳ" : a.kind === "care_plan" ? "Theo kế hoạch" : "Tái khám") }, { h: "Trạng thái", c: (a) => <Status d="appt" v={a.status} /> }]} onRow={() => go("chronic")} />
          </Card>
        )}
        {has("person.read") && has("encounter.write") && (
          <Card title="Chờ khám ban đầu" actions={<button className="btn sm" onClick={() => go("initial")}>Mở</button>} flat>
            <DataTable rows={waiting?.slice(0, 8)} empty={<Empty title="Không có ai đang chờ khám ban đầu" />}
              columns={[{ h: "Họ tên", c: (s) => <b>{s.person_name}</b> }, { h: "Tiếp nhận", c: (s) => fmtDate(s.start_date) }, { h: "Tiến độ", c: (s) => (s.initial_encounter_id ? <Badge tone="info">Đang khám</Badge> : <Badge tone="warn">Chưa khám</Badge>) }]} onRow={() => go("initial")} />
          </Card>
        )}
      </div>
    </>
  );
}
