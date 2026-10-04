// dist/chat.html: the page's own text, then the chat island (TA-C3). The server-rendered
// advisor pages load this bundle too (ADVISOR_ASSETS); they have no #chat-page-title.
import {CHAT_COPY} from './copy.ts';
import './chat.tsx';
// TA-W1: the same bundle runs on the server-rendered port, species and boat pages; this records their views and CTA clicks.
import './pages.ts';

const title = document.getElementById('chat-page-title'), intro = document.getElementById('chat-page-intro');
if (title) title.textContent = CHAT_COPY.pageTitle;
if (intro) intro.textContent = CHAT_COPY.pageIntro;
