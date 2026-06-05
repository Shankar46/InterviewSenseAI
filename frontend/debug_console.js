// Debug script for Career Accelerator troubleshooting
// Paste this entire script in the browser console (F12 → Console)

console.log("=".repeat(80));
console.log("CAREER ACCELERATOR DEBUG SCRIPT");
console.log("=".repeat(80));

// Test 1: Check if Store is working
console.log("\n1. Checking Store...");
if (typeof Store !== "undefined") {
  console.log("✓ Store exists");
  console.log("  - Current Chat ID:", Store.currentId);
  console.log("  - Total chats:", Store.getChatIds().length);
  const msgs = Store.getMessages(Store.currentId);
  console.log("  - Messages in current chat:", msgs.length);
  msgs.forEach((m, i) => {
    console.log(`    [${i}] ${m.role}: "${m.content.substring(0, 50)}..."`);
  });
} else {
  console.log("✗ Store not found!");
}

// Test 2: Check if UI is working
console.log("\n2. Checking UI...");
if (typeof UI !== "undefined") {
  console.log("✓ UI module exists");
  const msgWrap = document.getElementById("messages-wrap");
  if (msgWrap) {
    console.log("  ✓ messages-wrap element found");
    console.log("  - Child count:", msgWrap.children.length);
    console.log("  - HTML length:", msgWrap.innerHTML.length);
  } else {
    console.log("  ✗ messages-wrap element NOT found!");
  }
} else {
  console.log("✗ UI module not found!");
}

// Test 3: Check if API is working
console.log("\n3. Checking API...");
if (typeof Api !== "undefined") {
  console.log("✓ Api module exists");
  console.log("  - Testing health check...");
  Api.healthCheck?.() 
    ? console.log("    ✓ Health check method exists")
    : console.log("    - No health check method");
} else {
  console.log("✗ Api module not found!");
}

// Test 4: Check if Chat is working
console.log("\n4. Checking Chat...");
if (typeof Chat !== "undefined") {
  console.log("✓ Chat module exists");
  console.log("  - send method available:", typeof Chat.send === "function");
  console.log("  - bindKeyboard method available:", typeof Chat.bindKeyboard === "function");
} else {
  console.log("✗ Chat module not found!");
}

// Test 5: Check Config
console.log("\n5. Checking Config...");
if (typeof CONFIG !== "undefined") {
  console.log("✓ CONFIG exists");
  console.log("  - Backend URL:", CONFIG.BACKEND_URL);
  console.log("  - Career endpoint:", CONFIG.ENDPOINTS.CAREER);
  console.log("  - Stream delay:", CONFIG.STREAM_DELAY_MS, "ms");
} else {
  console.log("✗ CONFIG not found!");
}

// Test 6: Simulate a Career Request
console.log("\n6. Simulating Career Request...");
console.log("  Running: Api.generate({ topic: 'yes', ... })");

(async function() {
  try {
    const result = await Api.generate({
      topic: "yes",
      mode: "10 Marks",
      task: "career",
      history: [],
      file: null,
      assistantType: "career",
      careerConfig: {
        role: "Python Developer",
        duration: "30 days",
        hours_per_day: "2",
        level: "beginner",
        dsa_track: "yes"
      },
      chatId: Store.currentId || "test-" + Date.now()
    });

    console.log("  ✓ Response received!");
    console.log("    - text length:", result.text?.length || 0);
    console.log("    - text preview:", result.text?.substring(0, 80));
    console.log("    - has tracker:", !!result.tracker);
    console.log("    - tracker length:", result.tracker?.length || 0);
    console.log("    - full response:", JSON.stringify(result, null, 2).substring(0, 200) + "...");
  } catch (err) {
    console.error("  ✗ Request failed:", err.message);
  }
})();

console.log("\n" + "=".repeat(80));
console.log("DEBUG INFO ABOVE - Check for any ✗ marks");
console.log("=".repeat(80));
