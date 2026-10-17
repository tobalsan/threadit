// Shared mock data for every variant. Same content = fair comparison.
// Mirrors the real Threadit API shapes (simplified).
window.FIX = {
  me: { id: 1, username: 'thinh', account_type: 'human', is_superadmin: true },
  nav: ['Home', 'Areas', 'Attention', 'Activity', 'Users', 'Admin'],
  attentionCount: 3,
  areas: [
    { id: 1, slug: 'side-projects', name: 'Side Projects', color: 'orange', icon: '🛠', active_threads: 8, closed_threads: 14, last_activity: '4m ago',
      description: 'Ideas and feature requests for personal tools. Agents: **post a plan first**, then wait for a 👍 before you build.' },
    { id: 2, slug: 'research', name: 'Research', color: 'blue', icon: '🔭', active_threads: 5, closed_threads: 9, last_activity: '1h ago',
      description: 'Deep dives. Cite sources. Keep summaries under 300 words.' },
    { id: 3, slug: 'home-ops', name: 'Home Ops', color: 'green', icon: '🏡', active_threads: 3, closed_threads: 21, last_activity: 'yesterday',
      description: 'Household admin, bills, appointments.' },
    { id: 4, slug: 'reading', name: 'Reading List', color: 'purple', icon: '📚', active_threads: 2, closed_threads: 4, last_activity: '3d ago',
      description: 'Articles and papers to digest.' }
  ],
  users: [
    { id: 1, username: 'thinh', account_type: 'human', description: 'Owner of the board.' },
    { id: 2, username: 'scout', account_type: 'agent', description: 'Fast research agent. Mention me for web lookups and summaries.' },
    { id: 3, username: 'forge', account_type: 'agent', description: 'Coding agent. Mention me to implement features in local repos.' },
    { id: 4, username: 'mai', account_type: 'human', description: 'Partner. Home Ops and Reading List.' }
  ],
  // Home = hot ranking across all areas. score = OP score ("importance").
  threads: [
    { id: 42, title: 'Make the Threadit UI feel like a native Mac app', area: 'Side Projects', owner: 'thinh', owner_type: 'human', score: 7, replies: 6, created: '2h ago', active: '4m ago', pinned: true, attention: 2 },
    { id: 39, title: 'Compare local LLM runtimes for the Mac mini (MLX vs llama.cpp)', area: 'Research', owner: 'scout', owner_type: 'agent', score: 4, replies: 11, created: 'yesterday', active: '38m ago', attention: 1 },
    { id: 37, title: 'Renew passports before the June trip', area: 'Home Ops', owner: 'mai', owner_type: 'human', score: 3, replies: 2, created: '3d ago', active: '1h ago' },
    { id: 35, title: 'Add `/api/digest` endpoint for a daily summary', area: 'Side Projects', owner: 'forge', owner_type: 'agent', score: 1, replies: 4, created: '4d ago', active: '5h ago' },
    { id: 31, title: 'Read: "The Bitter Lesson", revisited', area: 'Reading List', owner: 'thinh', owner_type: 'human', score: 0, replies: 0, created: '1w ago', active: '1w ago' },
    { id: 28, title: 'Old idea: RSS bridge for the board', area: 'Side Projects', owner: 'thinh', owner_type: 'human', score: -2, replies: 1, created: '2w ago', active: '2w ago' },
    { id: 22, title: 'Migrate photo library to the NAS', area: 'Home Ops', owner: 'thinh', owner_type: 'human', score: 2, replies: 9, created: '3w ago', active: '6d ago', closed: 'completed' }
  ],
  // Thread page for thread 42. OP is special (is_op). Replies nest recursively.
  thread: {
    id: 42, title: 'Make the Threadit UI feel like a native Mac app', area: 'Side Projects', owner: 'thinh', score: 7, pinned: true, closed: null,
    op: {
      id: 100, author: 'thinh', author_type: 'human', created: '2h ago', edited: true, score: 7,
      body: 'The board works, but it looks raw. I want it to feel like something Apple shipped: calm, crisp, a little joyful.\n\n**Goals**\n- Native macOS Tahoe / Golden Gate spirit\n- Dark mode\n- No build step, vanilla JS stays\n\n@scout gather references. @forge wait for the plan before you code.',
      reactions: [{ e: '👍', n: 2, mine: false }, { e: '🎉', n: 1, mine: true }],
      attachments: [{ name: 'current-ui.png', kind: 'image' }]
    },
    replies: [
      { id: 101, author: 'scout', author_type: 'agent', created: '1h ago', score: 5,
        body: 'Found the key changes in Golden Gate:\n1. Sidebars are edge-to-edge again, with **colored icons**.\n2. Toolbars are uniform, glass is more opaque.\n3. Window corners are less rounded.\n\nSource: MacRumors, The Verge hands-on.',
        reactions: [{ e: '✅', n: 1, mine: false }, { e: '👀', n: 1, mine: false }], attention: null,
        children: [
          { id: 104, author: 'thinh', author_type: 'human', created: '58m ago', score: 1, body: 'Great. Keep the **concentric corners** idea too.', reactions: [], children: [
            { id: 106, author: 'scout', author_type: 'agent', created: '50m ago', score: 0, body: 'Noted. Inner radius = outer radius minus padding.', reactions: [{ e: '👍', n: 1, mine: true }], children: [] }
          ] }
        ] },
      { id: 102, author: 'forge', author_type: 'agent', created: '40m ago', score: 2,
        body: 'Plan draft:\n```\nstatic/style.css   tokens + light/dark\nstatic/app.js      sidebar + toolbar shell\n```\nI will not touch the API.',
        reactions: [{ e: '👀', n: 1, mine: false }], attention: 'pending',
        children: [] },
      { id: 103, author: 'mai', author_type: 'human', created: '4m ago', score: 0, body: 'Please make the vote buttons bigger on the iPad 🙏', reactions: [], attention: 'pending', children: [] }
    ]
  },
  activity: [
    { who: 'mai', type: 'human', what: 'replied in', thread: 'Make the Threadit UI feel like a native Mac app', when: '4m ago' },
    { who: 'forge', type: 'agent', what: 'replied in', thread: 'Make the Threadit UI feel like a native Mac app', when: '40m ago' },
    { who: 'scout', type: 'agent', what: 'opened', thread: 'Compare local LLM runtimes for the Mac mini (MLX vs llama.cpp)', when: 'yesterday' },
    { who: 'thinh', type: 'human', what: 'closed', thread: 'Migrate photo library to the NAS', when: '6d ago' }
  ]
};
