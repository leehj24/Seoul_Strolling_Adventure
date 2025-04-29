import os
import io
import base64
from flask import (
    Flask, render_template, request,
    redirect, url_for, session, flash
)
from flask_session import Session
from recommend import recommend
from busy_recommend import busy
from tour_recommend import tour
from config import THEMES, PREFERENCES

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-key")
app.config["SESSION_TYPE"] = "filesystem"
Session(app)

# 간단 메모리 사용자 저장소 (회원가입/로그인용)
users = {}  # { email: { "password": pw, "nickname": nick } }

# 세션 메시지 초기화
@app.before_request
def ensure_messages():
    session.setdefault("messages", [])

# 템플릿에서 current_user 사용
@app.context_processor
def inject_user():
    return dict(current_user=session.get("user"))

# ── 랜딩 (불필요하면 chat으로 바로 리다이렉트)
@app.route("/")
def index():
    return render_template("landing.html")

# ── 회원가입
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
        elif email in users:
            flash("이미 가입된 이메일입니다.")
        else:
            users[email] = {"password": pw, "nickname": nick}
            session["user"] = email
            flash(f"{nick}님, 회원가입 완료! 자동으로 로그인되었습니다.")
            return redirect(url_for("chat"))
    return render_template("signup.html")

# ── 로그인
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("username", "").strip()
        pw    = request.form.get("password", "")

        if not (email and pw):
            flash("이메일과 비밀번호를 모두 입력하세요.")
        elif email not in users or users[email]["password"] != pw:
            flash("이메일 또는 비밀번호가 올바르지 않습니다.")
        else:
            session["user"] = email
            flash(f"{users[email]['nickname']}님, 환영합니다!")
            return redirect(url_for("chat"))
    return render_template("login.html")

# ── 로그아웃
@app.route("/logout")
def logout():
    session.pop("user", None)
    flash("로그아웃 되었습니다.")
    return redirect(url_for("chat"))

# ── 채팅 인터페이스
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
            session["messages"].append({
                "sender": "bot",
                "text": "어떤 테마의 여행을 원하시나요? 2~3개를 선택해주세요."
            })
            session["state"] = "테마"

        elif state == "테마":
            themes = [
                t.strip() for t in request.form.get("themes", "").split(",")
                if t.strip()
            ]
            if not themes:
                session["messages"].append({
                    "sender": "bot",
                    "text": "테마를 선택해주세요."
                })
                return redirect(url_for("chat"))
            session["themes"] = themes
            session["messages"].append({
                "sender": "user",
                "text": ", ".join(themes)
            })
            session["messages"].append({
                "sender": "bot",
                "text": "여행 선호도를 순서대로 선택해주세요. (예: 인기도, 대중교통)"
            })
            session["state"] = "선호도"

        elif state == "선호도":
            prefs = [
                p.strip() for p in request.form.get("preferences", "").split(",")
                if p.strip()
            ]
            session["preferences"] = prefs
            session["messages"].append({
                "sender": "user",
                "text": ", ".join(prefs)
            })

            region = session.get("region")
            themes = session.get("themes")
            try:
                df_routes = recommend(region, themes)
                session["routes"] = df_routes.to_dict(orient="records")
                df_tour = tour(region, themes)
                session["tour_routes"] = df_tour.to_dict(orient="records")
                if df_routes.empty and df_tour.empty:
                    session["messages"].append({
                        "sender": "bot",
                        "text": "추천 결과가 없습니다."
                    })
            except Exception as e:
                session["messages"].append({
                    "sender": "bot",
                    "text": f"오류: {str(e)}"
                })

            session["state"] = "완료"

        else:
            # 첫 진입 또는 완료 후 '새 채팅하기'
            session["messages"] = [{"sender": "bot", "text": "안녕하세요! 여행 지역을 입력해주세요."}]
            session["state"] = "지역"

        return redirect(url_for("chat"))

    # GET: 첫 진입 시 초기 메시지 세팅
    if "state" not in session:
        session["messages"] = [{"sender": "bot", "text": "안녕하세요! 여행 지역을 입력해주세요."}]
        session["state"] = "지역"

    return render_template("chat.html", themes=THEMES, preferences=PREFERENCES)

# ── 대중교통 추천 상세
@app.route("/route/<int:idx>")
def route_detail(idx: int):
    routes = session.get('routes')
    if not routes or idx >= len(routes):
        flash("잘못된 경로이거나 세션이 만료되었습니다.")
        return redirect(url_for("chat"))
    row = routes[idx]
    legs = []
    for i in [1, 2]:
        if row.get(f"이동수단{i}"):
            legs.append({
                "no": i,
                "transport": row[f"이동수단{i}"],
                "start": row[f"타는곳{i}"],
                "end": row[f"내리는곳{i}"],
                "recs": [r.strip() for r in row[f"추천음식점{i}"].split(",") if r.strip()]
            })
    fig = busy(session.get('region'))
    img_io = io.BytesIO()
    fig.savefig(img_io, format='png')
    img_io.seek(0)
    busy_img_data = base64.b64encode(img_io.getvalue()).decode('utf-8')
    return render_template(
        "route_detail.html",
        title=row["단계"],
        subtitle=f"{session.get('region')} 일대 추천 코스",
        legs=legs,
        busy_img_data=busy_img_data
    )

# ── 인기도 추천 상세
@app.route("/tour_route/<int:idx>")
def tour_route_detail(idx: int):
    tour_routes = session.get('tour_routes')
    if not tour_routes or idx >= len(tour_routes):
        flash("잘못된 경로이거나 세션이 만료되었습니다.")
        return redirect(url_for("chat"))
    row = tour_routes[idx]
    fig = busy(session.get('region'))
    img_io = io.BytesIO()
    fig.savefig(img_io, format='png')
    img_io.seek(0)
    busy_img_data = base64.b64encode(img_io.getvalue()).decode('utf-8')
    return render_template(
        "tour_route_detail.html",
        title=row["추천장소"],
        subtitle=f"{session.get('region')} 일대 인기도 추천장소",
        details=row,
        busy_img_data=busy_img_data
    )

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
