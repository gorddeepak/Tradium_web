const { google } = require("@ai-sdk/google");

// Shared Gemini model for all AI features.
const MODEL_ID = "gemini-3.5-flash-lite";
const aiModel = google(MODEL_ID);

module.exports = { aiModel, MODEL_ID };
