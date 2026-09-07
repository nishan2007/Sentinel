(function () {
  "use strict";

  // Replace YOUR_PROJECT_REF with your Supabase project ref before publishing.
  // Keep this as the public Edge Function URL only. Never place service role keys
  // or other secrets in frontend JavaScript.
  const EDGE_FUNCTION_URL = "https://wbffhygkttoaaodjcvuh.supabase.co/functions/v1/wifi-captive-login";
  const FALLBACK_REDIRECT_URL = "https://www.google.com";

  const form = document.getElementById("wifiForm");
  const submitButton = document.getElementById("submitButton");
  const buttonText = submitButton.querySelector(".button-text");
  const statusMessage = document.getElementById("statusMessage");
  const timeGreeting = document.getElementById("timeGreeting");
  const portalTitle = document.getElementById("portal-title");
  const welcomeCopy = document.getElementById("welcomeCopy");

  const fields = {
    fullName: document.getElementById("fullName"),
    email: document.getElementById("email"),
    phone: document.getElementById("phone"),
    acceptedTerms: document.getElementById("acceptedTerms"),
    mac: document.getElementById("mac"),
    ip: document.getElementById("ip"),
    locationId: document.getElementById("locationId"),
    nasid: document.getElementById("nasid"),
    sessionId: document.getElementById("sessionId"),
    redirectUrl: document.getElementById("redirectUrl")
  };

  const queryValues = readCaptivePortalQuery();
  hydrateHiddenFields(queryValues);
  applyTimeGreeting();

  form.addEventListener("submit", handleSubmit);

  function readCaptivePortalQuery() {
    const params = new URLSearchParams(window.location.search);

    return {
      mac: params.get("mac") || "",
      ip: params.get("ip") || "",
      location_id: params.get("location_id") || "",
      nasid: params.get("nasid") || "",
      session_id: params.get("session_id") || "",
      redirect_url: params.get("redirect_url") || ""
    };
  }

  function hydrateHiddenFields(values) {
    fields.mac.value = values.mac;
    fields.ip.value = values.ip;
    fields.locationId.value = values.location_id;
    fields.nasid.value = values.nasid;
    fields.sessionId.value = values.session_id;
    fields.redirectUrl.value = values.redirect_url;
  }

  async function handleSubmit(event) {
    event.preventDefault();
    clearStatus();

    const validationError = validateForm();
    if (validationError) {
      showStatus(validationError, "error");
      return;
    }

    setLoading(true);

    try {
      const response = await fetch(EDGE_FUNCTION_URL, {
        method: "POST",
        headers: {
          "Content-Type": "application/json"
        },
        body: JSON.stringify(buildPayload())
      });

      if (!response.ok) {
        throw new Error("Captive portal request failed");
      }

      showStatus("You are connected. Enjoy your time with Sentinel.", "success");

      window.setTimeout(function () {
        window.location.assign(getRedirectTarget());
      }, 900);
    } catch (error) {
      showStatus("We could not connect you just yet. Please check your details and try again.", "error");
      setLoading(false);
    }
  }

  function validateForm() {
    const email = fields.email.value.trim();

    if (!fields.acceptedTerms.checked) {
      return "Please accept the WiFi Terms of Use to continue.";
    }

    if (email && !isValidEmail(email)) {
      return "Please enter a valid email address.";
    }

    return "";
  }

  function isValidEmail(email) {
    return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email);
  }

  function buildPayload() {
    return {
      full_name: fields.fullName.value.trim(),
      email: fields.email.value.trim(),
      phone: fields.phone.value.trim(),
      accepted_terms: fields.acceptedTerms.checked,
      mac_address: fields.mac.value,
      device_ip: fields.ip.value,
      location_id: fields.locationId.value || null,
      nas_id: fields.nasid.value,
      session_id: fields.sessionId.value,
      redirect_url: fields.redirectUrl.value,
      user_agent: window.navigator.userAgent,
      submitted_at: new Date().toISOString()
    };
  }

  function getRedirectTarget() {
    const redirectUrl = fields.redirectUrl.value.trim();

    if (!redirectUrl) {
      return FALLBACK_REDIRECT_URL;
    }

    try {
      const parsedUrl = new URL(redirectUrl, window.location.origin);

      if (parsedUrl.protocol === "https:" || parsedUrl.protocol === "http:") {
        return parsedUrl.href;
      }
    } catch (error) {
      return FALLBACK_REDIRECT_URL;
    }

    return FALLBACK_REDIRECT_URL;
  }

  function setLoading(isLoading) {
    submitButton.disabled = isLoading;
    submitButton.classList.toggle("is-loading", isLoading);
    buttonText.textContent = isLoading ? "Connecting..." : "Connect to Sentinel WiFi";
  }

  function applyTimeGreeting() {
    const hour = new Date().getHours();
    let greeting = "Welcome in";
    let title = "Settle in with Sentinel";
    let copy = "A few details, a quick hello, and you are connected to our complimentary guest WiFi.";

    if (hour >= 5 && hour < 12) {
      greeting = "Good morning";
      title = "Start your day with Sentinel";
      copy = "Step into the morning, take a breath, and connect to complimentary guest WiFi while you shop.";
    } else if (hour >= 12 && hour < 17) {
      greeting = "Good afternoon";
      title = "Take a moment with Sentinel";
      copy = "A little pause, a smooth connection, and our guest WiFi is yours while you are here.";
    } else if (hour >= 17 && hour < 22) {
      greeting = "Good evening";
      title = "Unwind with Sentinel";
      copy = "As the day softens, connect to complimentary guest WiFi and enjoy your time in store.";
    } else {
      greeting = "Welcome";
      title = "Thanks for stopping by Sentinel";
      copy = "Whenever you arrive, we are glad you are here. Connect to complimentary guest WiFi in a few quick steps.";
    }

    timeGreeting.textContent = greeting;
    portalTitle.textContent = title;
    welcomeCopy.textContent = copy;
  }

  function showStatus(message, type) {
    statusMessage.textContent = message;
    statusMessage.className = "status-message " + type;
    statusMessage.hidden = false;
  }

  function clearStatus() {
    statusMessage.textContent = "";
    statusMessage.className = "status-message";
    statusMessage.hidden = true;
  }
})();
