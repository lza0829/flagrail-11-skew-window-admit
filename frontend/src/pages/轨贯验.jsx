import React, { useEffect, useState } from "react";
import { get, post } from "../api.js";

export default function 轨贯验() {
  const [rows, setRows] = useState([]);
  const [讯, set讯] = useState("");
  const [报, set报] = useState(null);
  const 刷 = async () => setRows(await get("/贯验"));
  useEffect(() => { 刷().catch((e) => set讯(String(e))); }, []);

  const 跑 = async () => {
    const g = await post("/贯验");
    set报(g);
    await 刷();
    set讯(g.是否通过 ? "通过" : g.说明);
  };

  return (
    <div>
      <h1 className="题">轨贯验</h1>
      <p className="述">入轨版本 ↔ 下发票 ↔ 回读 ↔ 命运 互证。悬空下发 / 回读拧花 / 回滚无命运 → 不通过；超时间窗证不得混入正式确认集。</p>
      <div className="行">
        <button onClick={() => 跑().catch((e) => set讯(String(e)))}>跑贯验</button>
        <button className="次" onClick={() => 刷()}>刷新</button>
      </div>
      {讯 && <p className="讯">{讯}</p>}

      {报 && (
        <div className="轨刻">
          <span><i>正式确认</i><b>{报.正式确认数 ?? "—"}</b></span>
          <span><i>校正确认</i><b>{报.校正确认数 ?? 0}</b></span>
          <span><i>超窗排除</i><b>{报.超窗排除数 ?? 0}</b></span>
          <span>回读<b>{报.回读数}</b></span>
          <span>下发<b>{报.下发数}</b></span>
          <span className={"徽章 " + (报.是否通过 ? "通" : "败")}>{报.是否通过 ? "贯验通过" : "贯验失败"}</span>
        </div>
      )}

      {!rows.length ? <div className="空态">尚未跑过贯验</div> : (
        <table>
          <thead><tr><th>#</th><th>时刻</th><th>版本</th><th>下发</th><th>回读</th><th>命运</th><th>结果</th><th>说明</th></tr></thead>
          <tbody>{rows.map((r) => (
            <tr key={r.编号}><td>{r.编号}</td><td>{r.时刻}</td><td>{r.版本数}</td><td>{r.下发数}</td>
            <td>{r.回读数}</td><td>{r.命运数}</td>
            <td><span className={"徽章 " + (r.是否通过 ? "通" : "败")}>{r.是否通过 ? "通过" : "失败"}</span></td>
            <td>{r.说明}</td></tr>
          ))}</tbody>
        </table>
      )}
    </div>
  );
}
