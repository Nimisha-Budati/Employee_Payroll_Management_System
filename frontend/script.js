let selectedRole = "EMPLOYEE";

const API_URL = "http://127.0.0.1:8000/api";


function selectRole(role) {
    selectedRole = role;

    const employeeBtn = document.getElementById("employeeBtn");
    const adminBtn = document.getElementById("adminBtn");

    employeeBtn.classList.remove("active");
    adminBtn.classList.remove("active");

    if (role === "EMPLOYEE") {
        employeeBtn.classList.add("active");
    } else {
        adminBtn.classList.add("active");
    }

    const selectedRoleText = document.getElementById("selectedRoleText");
    if (selectedRoleText) {
        selectedRoleText.innerText =
            role === "ADMIN" ? "Signing in as Administrator" : "Signing in as Employee";
    }

    const loginSubmitText = document.getElementById("loginSubmitText");
    if (loginSubmitText) {
        loginSubmitText.innerText =
            role === "ADMIN" ? "Sign In as Administrator" : "Sign In as Employee";
    }
}


function showRegister() {
    document.getElementById("loginSection").style.display = "none";
    document.getElementById("registerSection").style.display = "block";
    document.getElementById("recoverySection").style.display = "none";

    const message = document.getElementById("registerMessage");

    if (message) {
        message.innerText = "";
    }
}


function showLogin() {
    document.getElementById("registerSection").style.display = "none";
    document.getElementById("recoverySection").style.display = "none";
    document.getElementById("loginSection").style.display = "block";

    const message = document.getElementById("loginMessage");

    if (message) {
        message.innerText = "";
    }
}

function showRecovery() {
    document.getElementById("loginSection").style.display = "none";
    document.getElementById("registerSection").style.display = "none";
    document.getElementById("recoverySection").style.display = "block";
    document.getElementById("recoveryMessage").innerText = "";
}


function togglePassword(id, button) {
    const input = document.getElementById(id);

    if (input.type === "password") {
        input.type = "text";
    } else {
        input.type = "password";
    }
}


async function register() {
    const username =
        document.getElementById("registerUsername").value.trim();

    const email =
        document.getElementById("registerEmail").value.trim();

    const password =
        document.getElementById("registerPassword").value;

    const confirmPassword =
        document.getElementById("confirmPassword").value;
    const role = document.getElementById("registerRole").value;

    const message =
        document.getElementById("registerMessage");

    message.innerText = "";

    if (!username || !email || !password || !confirmPassword) {
        message.innerText = "Please fill in all fields.";
        message.style.color = "#d9534f";
        return;
    }

    if (password !== confirmPassword) {
        message.innerText = "Passwords do not match.";
        message.style.color = "#d9534f";
        return;
    }

    try {
        const response = await fetch(
            API_URL + "/register/",
            {
                method: "POST",

                headers: {
                    "Content-Type": "application/json"
                },

                body: JSON.stringify({
                    username: username,
                    email: email,
                    password: password,
                    confirm_password: confirmPassword,
                    role: role
                })
            }
        );

        const data = await response.json();

        console.log("Register Status:", response.status);
        console.log("Register Response:", data);

        if (response.ok) {
            message.innerText =
                data.message || "Account created successfully.";

            message.style.color = "#176b45";

            document.getElementById("registerUsername").value = "";
            document.getElementById("registerEmail").value = "";
            document.getElementById("registerPassword").value = "";
            document.getElementById("confirmPassword").value = "";

            setTimeout(function() {
                showLogin();
            }, 1200);

        } else {
            message.innerText =
                data.error || "Registration failed.";

            message.style.color = "#d9534f";
        }

    } catch (error) {
        console.error("Register Error:", error);

        message.innerText =
            "Unable to connect to server.";

        message.style.color = "#d9534f";
    }
}


async function login() {
    const username =
        document.getElementById("loginUsername").value.trim();

    const password =
        document.getElementById("loginPassword").value;
    const rememberMe = document.getElementById("rememberMe").checked;

    const message =
        document.getElementById("loginMessage");

    message.innerText = "";

    if (!username || !password) {
        message.innerText =
            "Please enter username and password.";

        message.style.color = "#d9534f";

        return;
    }

    try {
        const response = await fetch(
            API_URL + "/login/",
            {
                method: "POST",

                headers: {
                    "Content-Type": "application/json"
                },

                credentials: "include",

                body: JSON.stringify({
                    username: username,
                    password: password,
                    role: selectedRole,
                    remember_me: rememberMe
                })
            }
        );

        const data = await response.json();

        console.log("Login Status:", response.status);
        console.log("Login Response:", data);

        if (response.ok) {
            message.innerText =
                data.message || "Login successful.";

            message.style.color = "#176b45";

            localStorage.setItem(
                "username",
                data.username
            );

            localStorage.setItem(
                "role",
                data.role
            );
            localStorage.setItem("accessToken", data.access);
            localStorage.setItem("refreshToken", data.refresh);

            setTimeout(function() {

                if (data.role === "ADMIN") {
                    window.location.href =
                        "admin-dashboard.html";
                } else {
                    window.location.href =
                        "employee-dashboard.html";
                }

            }, 700);

        } else {
            message.innerText =
                data.error || "Login failed.";

            message.style.color = "#d9534f";
        }

    } catch (error) {
        console.error("Login Error:", error);

        message.innerText =
            "Unable to connect to server.";

        message.style.color = "#d9534f";
    }
}

let recoveryResetToken = "";

async function requestOTP() {
    const message = document.getElementById("recoveryMessage");
    const email = document.getElementById("recoveryEmail").value.trim();
    if (!email) { message.innerText = "Enter your email or username."; return; }
    const response = await fetch(API_URL + "/password/forgot/", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ email }) });
    const data = await response.json();
    message.innerText = response.ok ? `${data.message} OTP: ${data.otp}` : (data.error || "Unable to generate OTP.");
    message.style.color = response.ok ? "#176b45" : "#d9534f";
}

async function verifyOTP() {
    const message = document.getElementById("recoveryMessage");
    const email = document.getElementById("recoveryEmail").value.trim();
    const otp = document.getElementById("recoveryOTP").value.trim();
    const response = await fetch(API_URL + "/password/verify-otp/", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ email, otp }) });
    const data = await response.json();
    recoveryResetToken = data.reset_token || "";
    message.innerText = response.ok ? "OTP verified. Set your new password." : (data.error || "OTP verification failed.");
    message.style.color = response.ok ? "#176b45" : "#d9534f";
}

async function resetPassword() {
    const message = document.getElementById("recoveryMessage");
    const password = document.getElementById("recoveryPassword").value;
    const confirmPassword = document.getElementById("recoveryConfirmPassword").value;
    const response = await fetch(API_URL + "/password/reset/", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ reset_token: recoveryResetToken, password, confirm_password: confirmPassword }) });
    const data = await response.json();
    message.innerText = response.ok ? "Password reset successfully. You can sign in now." : (data.error || "Password reset failed.");
    message.style.color = response.ok ? "#176b45" : "#d9534f";
    if (response.ok) setTimeout(showLogin, 900);
}

function googleLogin() {
    const message = document.getElementById("loginMessage");
    message.innerText = "Google authentication will be enabled after deployment.";
    message.style.color = "#176b45";
}


async function logoutUser() {
    try {
        await fetch(
            API_URL + "/logout/",
            {
                method: "POST",
                credentials: "include"
            }
        );
    } catch (error) {
        console.error("Logout Error:", error);
    }

    localStorage.removeItem("username");
    localStorage.removeItem("role");
    localStorage.removeItem("accessToken");
    localStorage.removeItem("refreshToken");

    window.location.href = "index.html";
}


function checkLogin() {
    const username =
        localStorage.getItem("username");

    const role =
        localStorage.getItem("role");

    if (!username || !role) {
        return;
    }

    console.log("Logged in user:", username);
    console.log("Role:", role);
}


selectRole("EMPLOYEE");
checkLogin();
