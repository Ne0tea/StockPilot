import test from 'node:test'
import assert from 'node:assert/strict'

import * as api from './index.js'

test('legacy analysis endpoints are no longer exported', () => {
  assert.equal('triggerAnalysis' in api, false)
  assert.equal('triggerAll' in api, false)
  assert.equal(typeof api.startInteractiveAnalysisWithMode, 'function')
})
