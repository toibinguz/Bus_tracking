/**
 * Node.js Kinematic Verification Suite (Dead Reckoning & Continuous Reconciliation).
 * Replaced legacy past-to-present tweening with Client-Side 1D Frenet Prediction & Continuous Reconciliation.
 */

const { spawnSync } = require('child_process');
const path = require('path');

console.log("\n" + "=".repeat(80));
console.log("KIỂM ĐỊNH ĐỘNG HỌC (NODE.JS): DEAD RECKONING FRENET & CONTINUOUS RECONCILIATION");
console.log("=".repeat(80));

const testPath = path.join(__dirname, 'test_dead_reckoning_kinematics.js');
const res = spawnSync(process.execPath, [testPath], { stdio: 'inherit' });

if (res.status !== 0) {
    process.exit(res.status || 1);
}
process.exit(0);
