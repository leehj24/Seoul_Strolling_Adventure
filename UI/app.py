import os
import io
import base64
from flask import (
    Flask, render_template, request,
    redirect, url_for, session, flash
)
from flask_session import Session
from recommend import recommend
from tour_recommend import tour
from config import THEMES, PREFERENCES

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-key")
app.config["SESSION_TYPE"] = "filesystem"
Session(app)

users = {}

@app.before_request
def ensure_messages():
    session.setdefault("messages", [])

@app.context_processor
def inject_user():
    user_email = session.get("user")
    user_nick = users[user_email]["nickname"] if user_email and user_email in users else None
    return dict(current_user=user_email, current_nickname=user_nick)

@app.route("/")
def index():
    return render_template("landing.html")

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
        elif email in users:
            flash("이미 가입된 이메일입니다.")
        else:
            users[email] = {"password": pw, "nickname": nick}
            session["user"] = email
            flash(f"{nick}님, 회원가입 완료! 자동으로 로그인되었습니다.")
            return redirect(url_for("chat"))
    return render_template("signup.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("username", "").strip()
        pw = request.form.get("password", "")

        if not (email and pw):
            flash("이메일과 비밀번호를 모두 입력하세요.")
        elif email not in users or users[email]["password"] != pw:
            flash("이메일 또는 비밀번호가 올바르지 않습니다.")
        else:
            session["user"] = email
            flash(f"{users[email]['nickname']}님, 환영합니다!")
            return redirect(url_for("chat"))
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.pop("user", None)
    flash("로그아웃 되었습니다.")
    return redirect(url_for("chat"))

@app.route("/chat", methods=["GET", "POST"])
def chat():
    if "user" not in session:
        flash("로그인이 필요합니다.")
        return redirect(url_for("login"))

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
            session["messages"] = [{"sender": "bot", "text": "안녕하세요! 여행 지역을 입력해주세요."}]
            session["state"] = "지역"

        return redirect(url_for("chat"))

    if "state" not in session:
        session["messages"] = [{"sender": "bot", "text": "안녕하세요! 여행 지역을 입력해주세요."}]
        session["state"] = "지역"

    return render_template("chat.html", themes=THEMES, preferences=PREFERENCES)

@app.route("/reset")
def reset_chat():
    session.clear()
    session["messages"] = [{"sender": "bot", "text": "안녕하세요! 여행 지역을 입력해주세요."}]
    session["state"] = "지역"
    return redirect(url_for("chat"))

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
                "recs": [r.strip() for r in row.get(f"추천장소{i}", "").split(",") if r.strip()]
            })

    # 혼잡도 그래프 로딩 (row_{idx}_spline.png)
    busy_img_data = None
    img_path = f"plots/row_{idx}_spline.png"
    if os.path.exists(img_path):
        with open(img_path, "rb") as f:
            busy_img_data = base64.b64encode(f.read()).decode()

    return render_template(
        "route_detail.html",
        title=row.get("단계", f"추천 경로 {idx+1}"),
        subtitle=f"{session.get('region')} 일대 추천 코스",
        legs=legs,
        busy_img_data=busy_img_data
    )

@app.route("/tour_route/<int:idx>")
def tour_route_detail(idx: int):
    tour_routes = session.get('tour_routes')
    if not tour_routes or idx >= len(tour_routes):
        flash("잘못된 경로이거나 세션이 만료되었습니다.")
        return redirect(url_for("chat"))

    row = tour_routes[idx]

    # 혼잡도 그래프 로딩 (row_{idx}_spline2.png)
    busy_img_data = None
    img_path = f"plots/row_{idx}_spline2.png"
    if os.path.exists(img_path):
        with open(img_path, "rb") as f:
            busy_img_data = base64.b64encode(f.read()).decode()

    return render_template(
        "tour_route_detail.html",
        title=row.get("추천장소", f"추천 경로 {idx+1}"),
        subtitle=f"{session.get('region')} 일대 인기도 추천장소",
        details=row,
        busy_img_data=busy_img_data
    )

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
