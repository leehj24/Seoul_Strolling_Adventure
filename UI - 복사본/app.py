import os
from flask import (
    Flask, render_template, request,
    redirect, url_for, session, flash
)
from recommend import recommend

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-key")

# ─────────────────────────────────────────────────────────
@app.before_request
def ensure_messages():
    session.setdefault("messages", [])

# ── 랜딩 ────────────────────────────────────────────────
@app.route("/")
def index():
    return render_template("landing.html")

# ── 로그인 ─────────────────────────────────────────────
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("username", "").strip()
        pw    = request.form.get("password", "")
        if email and pw:
            session["user"] = email
            flash(f"{email}님, 환영합니다!")
            return redirect(url_for("index"))
        flash("이메일과 비밀번호를 모두 입력하세요.")
    return render_template("login.html")

# ── 회원가입 ───────────────────────────────────────────
@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        email = request.form.get("username", "").strip()
        nick  = request.form.get("nickname", "").strip()
        pw    = request.form.get("password", "")
        conf  = request.form.get("confirm", "")
        if not (email and nick and pw and conf):
            flash("모든 필드를 입력해주세요.")
        elif pw != conf:
            flash("비밀번호가 일치하지 않습니다.")
        else:
            flash("회원가입 완료! 로그인 해주세요.")
            return redirect(url_for("login"))
    return render_template("signup.html")

# ── 시작 ───────────────────────────────────────────────
@app.route("/start")
def start():
    session.clear()
    session["messages"] = [{"sender":"bot","text":"안녕하세요! 여행 지역을 입력해주세요."}]
    session["state"] = "지역"
    return redirect(url_for("chat"))

# ── 채팅 ───────────────────────────────────────────────
@app.route("/chat", methods=["GET", "POST"])
def chat():
    if request.method == "POST":
        state = session.get("state")

        # 지역
        if state == "지역":
            region = request.form.get("message", "").strip()
            if not region:
                return redirect(url_for("chat"))
            session["region"] = region
            session["messages"].append({"sender":"user","text":region})
            session["messages"].append({"sender":"bot","text":"어떤 테마의 여행을 원하시나요? 2~3개를 선택해주세요."})
            session["state"] = "테마"

        # 테마
        elif state == "테마":
            themes = [t.strip() for t in request.form.get("themes", "").split(",") if t.strip()]
            if not themes:
                session["messages"].append({"sender":"bot","text":"테마를 입력해주세요."})
                return redirect(url_for("chat"))
            session["themes"] = themes
            session["messages"].append({"sender":"user","text":", ".join(themes)})
            session["messages"].append({"sender":"bot","text":"여행 선호도를 순서대로 입력해주세요. (예: 인기도,대중교통,보행)"})
            session["state"] = "선호도"

        # 선호도 ➜ 추천
        elif state == "선호도":
            prefs = [p.strip() for p in request.form.get("preferences", "").split(",") if p.strip()]
            session["messages"].append({"sender":"user","text":", ".join(prefs)})

            region  = session.get("region")
            themes  = session.get("themes")
            try:
                df_routes = recommend(region, themes)
                session["routes"] = df_routes.to_dict(orient="records")
                if df_routes.empty:
                    session["messages"].append({"sender":"bot","text":"추천 결과가 없습니다."})
            except Exception as e:
                session["messages"].append({"sender":"bot","text":str(e)})
            session["state"] = "완료"

        # 완료 상태에서 추가 입력 시 안내
        else:
            session["messages"].append({"sender":"bot","text":"새로 시작하려면 ‘새 채팅하기’ 버튼을 눌러주세요."})

        return redirect(url_for("chat"))

    return render_template("chat.html")

# ── 추천경로 상세 ──────────────────────────────────────────
@app.route("/route/<int:idx>")
def route_detail(idx: int):
    routes = session.get("routes")          # list[dict]  (chat 단계에서 저장해둔 것)
    if not routes or idx >= len(routes):
        flash("잘못된 경로이거나 세션이 만료되었습니다.")
        return redirect(url_for("chat"))

    row = routes[idx]                       # 선택된 DataFrame 한 행 → dict

    # ── 구간(leg) 1, 2 정보를 카드용 리스트로 변환 ──
    legs = [
        {
            "no": 1,
            "transport": row["이동수단1"],
            "start": row["타는곳1"],
            "end":   row["내리는곳1"],
            "recs":  [r.strip() for r in row["추천음식점1"].split(",") if r.strip()]
        },
        {
            "no": 2,
            "transport": row["이동수단2"],
            "start": row["타는곳2"],
            "end":   row["내리는곳2"],
            "recs":  [r.strip() for r in row["추천음식점2"].split(",") if r.strip()]
        }
    ]
    # 빈 값(두 번째 구간이 없을 수도 있음) 걸러내기
    legs = [leg for leg in legs if leg["transport"]]

    return render_template(
        "route_detail.html",
        title=row["단계"],
        subtitle=f"{session.get('region')} 일대 추천 코스",
        legs=legs
    )

# ── 로그아웃 ───────────────────────────────────────────
@app.route("/logout")
def logout():
    session.clear()
    flash("로그아웃 되었습니다.")
    return redirect(url_for("index"))

if __name__ == "__main__":
    app.run(debug=True)