import React, { useEffect, useState } from "react";
import { get, post, postFixture } from "../api.js";

const 口径A = "以窗拒为准";
const 口径B = "以中心校正收证为准";

function 结果徽章(r) {
  if (r.结果 === "确认") return <span className="徽章 通">确认</span>;
  if (r.结果 === "偏差") return <span className="徽章 警">偏差</span>;
  if (r.结果 === "并发去重") return <span className="徽章 信">并发去重</span>;
  return <span className="徽章 败">{r.结果 || "拒绝"}</span>;
}

export default function 回读台() {
  const [rows, setRows] = useState([]);
  const [pol, setPol] = useState({ 口径: 口径A, 允许漂移秒: 300 });
  const [讯, set讯] = useState("");
  const [票号, set票号] = useState("");
  const [门, set门] = useState(null);

  const 刷 = async () => {
    const [rs, p] = await Promise.all([get("/回读证"), get("/时间窗策略")]);
    setRows(rs);
    setPol(p);
  };
  useEffect(() => { 刷().catch((e) => set讯(String(e))); }, []);

  const 灌 = async (名) => {
    set讯("装载中…");
    try {
      const r = await postFixture(名);
      await 刷();
      const g = r?.报告?.放量门;
      set讯(g ? `已灌「${名}」· 正式确认 ${g.正式确认数} · 可放量 ${g.可放量 ? "是" : "否"}` : `已灌「${名}」`);
    } catch (e) {
      set讯(String(e));
    }
  };

  const 切口径 = async (口径) => {
    set讯("切换策略…");
    try {
      const p = await post("/时间窗策略", { 收证口径: 口径, 允许漂移秒: pol.允许漂移秒 });
      setPol(p);
      set讯(`口径已切：${p.口径}（既有证不重裁，新回读按此裁决）`);
    } catch (e) {
      set讯(String(e));
    }
  };

  const 查门 = async () => {
    if (!票号.trim()) return;
    try {
      set门(await get(`/放量门?票号=${encodeURIComponent(票号.trim())}`));
    } catch (e) {
      set讯(String(e));
    }
  };

  return (
    <div>
      <h1 className="题">回读台 · 时间窗核证</h1>
      <p className="述">
        边缘钟漂会让回读时间戳落在下发前。三联核证 <b>下发时 / 边缘时 / 中心校正时</b>：
        超允许漂移两端硬拒；口径可在「以窗拒为准（逆序即无正式证）」与「中心校正收证（标记校正）」间二选。
      </p>

      <div className="策略条">
        <span className="策略签">时间窗口径</span>
        <button className={pol.口径 === 口径A ? "信" : "次"} onClick={() => 切口径(口径A)}>
          以窗拒为准
        </button>
        <button className={pol.口径 === 口径B ? "信" : "次"} onClick={() => 切口径(口径B)}>
          以中心校正收证为准
        </button>
        <span className="策略漂">允许漂移 {pol.允许漂移秒}s</span>
        <span className={"徽章 " + (pol.口径 === 口径B ? "警" : "通")}>当前：{pol.口径}</span>
      </div>

      <div className="行">
        <button onClick={() => 灌("回读样例")}>灌常规回读样例</button>
        <button className="次" onClick={() => 灌("时间窗-正常时序")}>夹具·正常时序</button>
        <button className="次" onClick={() => 灌("时间窗-逆序")}>夹具·逆序(窗拒)</button>
        <button className="次" onClick={() => 灌("时间窗-超大漂移")}>夹具·超大漂移两端</button>
        <button className="次" onClick={() => 灌("时间窗-并发双回读")}>夹具·并发双回读</button>
        <button className="次" onClick={() => 灌("时间窗-校正收证")}>夹具·校正收证分叉</button>
        <button className="次" onClick={() => 刷().catch((e) => set讯(String(e)))}>刷新</button>
      </div>

      <div className="行">
        <input
          className="输入"
          value={票号}
          placeholder="输入票号查放量门，如 票-tw-reverse"
          onChange={(e) => set票号(e.target.value)}
        />
        <button className="次" onClick={查门}>查放量门</button>
        {门 && (
          <span className="门果">
            {门.票号} · 正式确认 <b>{门.正式确认数}</b> · 排除 <b>{门.排除数}</b> ·{" "}
            <span className={"徽章 " + (门.可放量 ? "通" : "败")}>{门.可放量 ? "可放量" : "不可放量"}</span>
            {门.校正确认集?.length > 0 && <span className="徽章 警">校正 {门.校正确认集.length}</span>}
          </span>
        )}
      </div>

      {讯 && <p className="讯">{讯}</p>}

      {!rows.length ? <div className="空态">尚无回读证，先灌样例或时间窗夹具</div> : (
        <div className="表卷">
          <table className="时间表">
            <thead>
              <tr>
                <th>证号</th><th>票号</th><th>边缘</th><th>结果</th><th>窗裁决</th>
                <th>原始边缘时</th><th>中心收证时</th><th>校正标记</th><th>valid</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.证号} className={r.正式确认 ? "" : "灰行"}>
                  <td className="mono">{r.证号}</td>
                  <td className="mono">{r.票号}</td>
                  <td>{r.边缘键}</td>
                  <td>{结果徽章(r)}</td>
                  <td>
                    <span className="裁决码">{r.窗裁决 || "—"}</span>
                    {r.逆序 ? <span className="小签 败签">逆序</span> : null}
                    {r.超漂移 ? <span className="小签 败签">超漂移</span> : null}
                  </td>
                  <td className="mono 时刻">{r.原始边缘时 || r.边缘时 || "—"}</td>
                  <td className="mono 时刻">{r.中心收证时 || r.中心时 || "—"}</td>
                  <td>
                    {r.是否校正
                      ? <span className="徽章 警">已校正</span>
                      : <span className="淡">—</span>}
                  </td>
                  <td>
                    <span className={"徽章 " + (r.valid ? "通" : "败")}>
                      {r.valid ? "valid" : "invalid"}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <p className="述 脚注">
        正式确认集谓词：结果=确认 且 正式确认=1 且 valid=1。超窗/逆序被拒证、并发去重证均不进集合，
        贯验与放量门同口径。自动化：<code>scripts/时间窗_逆序.py</code> 与{" "}
        <code>scripts/时间窗_超大漂移.py</code> 分开跑。
      </p>
    </div>
  );
}
