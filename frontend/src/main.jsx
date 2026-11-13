import { Component, StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App.jsx";
import { Overlays, applyTheme, getTheme } from "./ui.jsx";
import "./styles.css";

/** Lỗi hiển thị không được làm trắng cả ứng dụng: báo rõ và cho tải lại. */
class ErrorBoundary extends Component {
  state = { err: null };
  static getDerivedStateFromError(err) { return { err }; }
  componentDidCatch(err, info) { console.error("UI error:", err, info?.componentStack); }
  render() {
    if (!this.state.err) return this.props.children;
    return (
      <div className="login"><div className="card"><div className="cb">
        <h2>Đã xảy ra lỗi hiển thị</h2>
        <p className="muted">Dữ liệu của bạn không bị ảnh hưởng. Hãy tải lại trang; nếu lỗi lặp lại, báo cho bộ phận quản trị kèm thời điểm xảy ra.</p>
        <button className="btn primary" onClick={() => location.reload()}>Tải lại trang</button>
      </div></div></div>
    );
  }
}

applyTheme(getTheme());   // mặc định giao diện sáng
createRoot(document.getElementById("root")).render(<StrictMode><ErrorBoundary><Overlays><App /></Overlays></ErrorBoundary></StrictMode>);
