const employeeNavigation = document.createElement('script'); employeeNavigation.src = 'employee-navigation.js'; document.head.appendChild(employeeNavigation);
const employeeNavigationCss = document.createElement('link'); employeeNavigationCss.rel = 'stylesheet'; employeeNavigationCss.href = 'employee-navigation.css'; document.head.appendChild(employeeNavigationCss);
const API_URL = "http://127.0.0.1:8000/api";

let username = localStorage.getItem("username");
let role = localStorage.getItem("role");

if (!username || role !== "EMPLOYEE") {
    window.location.href = "index.html";
}

document.getElementById("headerUsername").innerText = username;

const startDate = document.getElementById("startDate");
const endDate = document.getElementById("endDate");
const numberOfDays = document.getElementById("numberOfDays");
const leaveForm = document.getElementById("leaveForm");
const leaveMessage = document.getElementById("leaveMessage");


function calculateDays() {

    if (!startDate.value || !endDate.value) {
        numberOfDays.value = "";
        return;
    }

    const start = new Date(startDate.value);
    const end = new Date(endDate.value);

    if (end < start) {
        numberOfDays.value = "";
        return;
    }

    const difference = end - start;

    const days = Math.floor(
        difference / (1000 * 60 * 60 * 24)
    ) + 1;

    numberOfDays.value = days + " day" + (days > 1 ? "s" : "");
}


startDate.addEventListener("change", function() {
    endDate.min = startDate.value;
    calculateDays();
});


endDate.addEventListener("change", function() {
    calculateDays();
});


leaveForm.addEventListener("submit", async function(event) {

    event.preventDefault();

    leaveMessage.innerText = "";
    leaveMessage.className = "";

    const leaveType =
        document.getElementById("leaveType").value;

    const start =
        startDate.value;

    const end =
        endDate.value;

    const reason =
        document.getElementById("reason").value.trim();

    if (!leaveType || !start || !end || !reason) {

        leaveMessage.innerText =
            "Please fill in all fields.";

        leaveMessage.className =
            "error-message";

        return;
    }

    if (end < start) {

        leaveMessage.innerText =
            "End date cannot be before start date.";

        leaveMessage.className =
            "error-message";

        return;
    }

    const submitButton =
        document.querySelector(".submit-btn");

    submitButton.disabled = true;
    submitButton.innerText = "Submitting...";

    try {

        const response = await fetch(
            API_URL + "/leaves/",
            {
                method: "POST",

                headers: {
                    "Content-Type": "application/json"
                },

                credentials: "include",

                body: JSON.stringify({
                    leave_type: leaveType,
                    start_date: start,
                    end_date: end,
                    reason: reason
                })
            }
        );

        const data = await response.json();

        if (response.ok) {

            leaveMessage.innerText =
                data.message || "Leave application submitted successfully.";

            leaveMessage.className =
                "success-message";

            leaveForm.reset();

            numberOfDays.value = "";

            endDate.min = "";

            loadLeaveRequests();

        } else {

            leaveMessage.innerText =
                data.error || "Unable to submit leave request.";

            leaveMessage.className =
                "error-message";
        }

    } catch (error) {

        console.error("Leave Error:", error);

        leaveMessage.innerText =
            "Unable to connect to server.";

        leaveMessage.className =
            "error-message";
    }

    submitButton.disabled = false;
    submitButton.innerText = "Submit Leave Request";
});


async function loadLeaveRequests() {

    const tableBody =
        document.getElementById("leaveTableBody");

    tableBody.innerHTML = `
        <tr>
            <td colspan="7" class="loading">
                Loading leave requests...
            </td>
        </tr>
    `;

    try {

        const response = await fetch(
            API_URL + "/leaves/",
            {
                method: "GET",
                credentials: "include"
            }
        );

        const data = await response.json();

        if (!response.ok) {

            tableBody.innerHTML = `
                <tr>
                    <td colspan="7" class="empty">
                        ${data.error || "Unable to load leave requests."}
                    </td>
                </tr>
            `;

            return;
        }

        // The API returns the serialized list directly.  Accept the previous
        // wrapped shape too, so this page remains compatible with either API.
        const leaves = Array.isArray(data) ? data : (data.leaves || []);

        updateSummary(leaves);

        if (leaves.length === 0) {

            tableBody.innerHTML = `
                <tr>
                    <td colspan="7" class="empty">
                        No leave requests found.
                    </td>
                </tr>
            `;

            return;
        }

        tableBody.innerHTML = "";

        leaves.forEach(function(leave) {

            const row =
                document.createElement("tr");

            let statusClass = "";

            if (leave.status === "PENDING") {
                statusClass = "status-pending";
            } else if (leave.status === "APPROVED") {
                statusClass = "status-approved";
            } else if (leave.status === "REJECTED") {
                statusClass = "status-rejected";
            }

            let statusText =
                leave.status.charAt(0) +
                leave.status.slice(1).toLowerCase();

            let reasonText =
                leave.reason;

            if (
                leave.status === "REJECTED" &&
                leave.rejection_reason
            ) {
                reasonText +=
                    " - Rejected: " +
                    leave.rejection_reason;
            }

            row.innerHTML = `
                <td>${escapeHTML(leave.leave_type)}</td>
                <td>${escapeHTML(leave.start_date)}</td>
                <td>${escapeHTML(leave.end_date)}</td>
                <td>${leave.number_of_days}</td>
                <td>${escapeHTML(reasonText)}</td>
                <td>
                    <span class="status ${statusClass}">
                        ${statusText}
                    </span>
                </td>
                <td>${escapeHTML(leave.applied_at)}</td>
            `;

            tableBody.appendChild(row);
        });

    } catch (error) {

        console.error("Load Leave Error:", error);

        tableBody.innerHTML = `
            <tr>
                <td colspan="7" class="empty">
                    Unable to connect to server.
                </td>
            </tr>
        `;
    }
}


function updateSummary(leaves) {

    let pending = 0;
    let approved = 0;
    let rejected = 0;

    leaves.forEach(function(leave) {

        if (leave.status === "PENDING") {
            pending++;
        }

        if (leave.status === "APPROVED") {
            approved++;
        }

        if (leave.status === "REJECTED") {
            rejected++;
        }
    });

    document.getElementById("pendingCount").innerText =
        pending;

    document.getElementById("approvedCount").innerText =
        approved;

    document.getElementById("rejectedCount").innerText =
        rejected;
}


function escapeHTML(value) {

    const div = document.createElement("div");

    div.innerText = value || "";

    return div.innerHTML;
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

        console.log(error);
    }

    localStorage.clear();

    window.location.href = "index.html";
}


loadLeaveRequests();
