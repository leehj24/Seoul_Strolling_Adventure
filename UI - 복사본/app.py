import os
import io
import base64
from flask import (
    Flask, render_template, request,
    redirect, url_for, session, flash
)
from flask_session import Session  # ★ 추가
from recommend import recommend
from busy_recommend import busy
from tour_recommend import tour

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-key")

# ── Flask-Session 설정 (서버 세션 저장) ───────────────────────
app.config["SESSION_TYPE"] = "filesystem"  # 서버 파일시스템에 저장
Session(app)



@app.before_request
def ensure_messages():
    session.setdefault("messages", [])

# ── 랜딩 ─────────────────
@app.route("/")
def index():
    return render_template("landing.html")

# ── 로그인 ────────────────
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("username", "").strip()
        pw = request.form.get("password", "")
        if email and pw:
            session["user"] = email
            flash(f"{email}님, 환영합니다!")
            return redirect(url_for("index"))
        flash("이메일과 비밀번호를 모두 입력하세요.")
    return render_template("login.html")

# ── 회원가입 ───────────────
@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        email = request.form.get("username", "").strip()
        nick = request.form.get("nickname", "").strip()
        pw = request.form.get("password", "")
        conf = request.form.get("confirm", "")
        if not (email and nick and pw and conf):
            flash("모든 필드를 입력해주세요.")
        elif pw != conf:
            flash("비밀번호가 일치하지 않습니다.")
        else:
            flash("회원가입 완료! 로그인 해주세요.")
            return redirect(url_for("login"))
    return render_template("signup.html")

# ── 시작 ──────────────────
@app.route("/start")
def start():
    session.clear()
    session["messages"] = [{"sender": "bot", "text": "안녕하세요! 여행 지역을 입력해주세요."}]
    session["state"] = "지역"
    return redirect(url_for("chat"))

# ── 채팅 ──────────────────
@app.route("/chat", methods=["GET", "POST"])
def chat():
    if request.method == "POST":
        state = session.get("state")

        if state == "지역":
            region = request.form.get("message", "").strip()
            if not region:
                return redirect(url_for("chat"))
            session["region"] = region
            session["messages"].append({"sender": "user", "text": region})
            session["messages"].append({"sender": "bot", "text": "어떤 테마의 여행을 원하시나요? 2~3개를 선택해주세요."})
            session["state"] = "테마"

        elif state == "테마":
            themes = [t.strip() for t in request.form.get("themes", "").split(",") if t.strip()]
            if not themes:
                session["messages"].append({"sender": "bot", "text": "테마를 입력해주세요."})
                return redirect(url_for("chat"))
            session["themes"] = themes
            session["messages"].append({"sender": "user", "text": ", ".join(themes)})
            session["messages"].append({"sender": "bot", "text": "여행 선호도를 순서대로 입력해주세요. (예: 인기도, 대중교통)"})
            session["state"] = "선호도"

        elif state == "선호도":
            prefs = [p.strip() for p in request.form.get("preferences", "").split(",") if p.strip()]
            session["preferences"] = prefs
            session["messages"].append({"sender": "user", "text": ", ".join(prefs)})

            region = session.get("region")
            themes = session.get("themes")
            try:
                df_routes = recommend(region, themes)
                df_tour = tour(region, themes)
                session["routes"] = df_routes.to_dict(orient="records")
                session["tour_routes"] = df_tour.to_dict(orient="records")
                if df_routes.empty and df_tour.empty:
                    session["messages"].append({"sender": "bot", "text": "추천 결과가 없습니다."})
            except Exception as e:
                session["messages"].append({"sender": "bot", "text": str(e)})
            session["state"] = "완료"

        else:
            session["messages"].append({"sender": "bot", "text": "새로 시작하려면 ‘새 채팅하기’ 버튼을 눌러주세요."})

        return redirect(url_for("chat"))

    return render_template("chat.html")

# ── 대중교통 추천 상세 ────────────────────
@app.route("/route/<int:idx>")
def route_detail(idx: int):
    routes = session.get('routes')
    if not routes or idx >= len(routes):
        flash("잘못된 경로이거나 세션이 만료되었습니다.")
        return redirect(url_for("chat"))

    row = routes[idx]
    legs = [
        {
            "no": 1,
            "transport": row["이동수단1"],
            "start": row["타는곳1"],
            "end": row["내리는곳1"],
            "recs": [r.strip() for r in row["추천음식점1"].split(",") if r.strip()]
        },
        {
            "no": 2,
            "transport": row["이동수단2"],
            "start": row["타는곳2"],
            "end": row["내리는곳2"],
            "recs": [r.strip() for r in row["추천음식점2"].split(",") if r.strip()]
        }
    ]
    legs = [leg for leg in legs if leg["transport"]]

    region = session.get('region')
    if region:
        fig = busy(region)
        img_io = io.BytesIO()
        fig.savefig(img_io, format='png')
        img_io.seek(0)
        busy_img_data = base64.b64encode(img_io.getvalue()).decode('utf-8')
    else:
        busy_img_data = None

    return render_template(
        "route_detail.html",
        title=row["단계"],
        subtitle=f"{session.get('region')} 일대 추천 코스",
        legs=legs,
        busy_img_data=busy_img_data
    )

# ── 인기도 추천 상세 ────────────────────
@app.route("/tour_route/<int:idx>")
def tour_route_detail(idx: int):
    routes = session.get('tour_routes')
    if not routes or idx >= len(routes):
        flash("잘못된 경로이거나 세션이 만료되었습니다.")
        return redirect(url_for("chat"))

    row = routes[idx]
    legs = [
        {
            "no": 1,
            "place": row["추천장소"],
            "walk_km": row["도보이동km_1"],
            "recs": [r.strip() for r in row["추천장소2"].split(",") if r.strip()]
        },
        {
            "no": 2,
            "place": row["추천장소2"],
            "walk_km": row["도보이동km_2"],
            "recs": [r.strip() for r in row["추천장소3"].split(",") if r.strip()]
        }
    ]

    return render_template(
        "tour_route_detail.html",
        title=row["추천장소"],
        subtitle=f"{session.get('region')} 주변 추천 코스",
        legs=legs
    )

# ── 로그아웃 ──────────────
@app.route("/logout")
def logout():
    session.clear()
    flash("로그아웃 되었습니다.")
    return redirect(url_for("index"))

# ── 서버 실행 ──────────────
if __name__ == "__main__":
    app.run(debug=True)
