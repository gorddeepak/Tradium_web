const express = require('express');
const { chatWithAssistant } = require('../controllers/assistantController');
const { protect } = require('../middlewares/auth'); // your existing JWT middleware
const { generatePageInsight, generateDashboardBriefing } = require('../controllers/insightController');

const router = express.Router();
router.post('/chat', protect, chatWithAssistant);
router.post('/insight', protect, generatePageInsight);
router.post('/briefing', protect, generateDashboardBriefing);
module.exports = router;
