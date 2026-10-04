// dist/chat.html: the page's own text, then the chat island (TA-C3).
import {CHAT_COPY} from './copy.ts';
import './chat.tsx';

const title = document.getElementById('chat-page-title'), intro = document.getElementById('chat-page-intro');
if (title) title.textContent = CHAT_COPY.pageTitle;
if (intro) intro.textContent = CHAT_COPY.pageIntro;
