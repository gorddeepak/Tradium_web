const express = require("express");
const rateLimit = require("express-rate-limit");
const router = express.Router();
const { signup, login, logout, getMe } = require("../controllers/authController");
const { protect } = require("../middlewares/auth");

// Login/signup are the brute-forceable endpoints — 20 attempts per 15 min per IP.
const authLimiter = rateLimit({
  windowMs: 15 * 60 * 1000,
  limit: 20,
  standardHeaders: "draft-7",
  legacyHeaders: false,
  message: { message: "Too many attempts. Try again in a few minutes." },
});

router.post("/signup", authLimiter, signup);
router.post("/login", authLimiter, login);
router.post("/logout", logout);
router.get("/me", protect, getMe);

module.exports = router;
