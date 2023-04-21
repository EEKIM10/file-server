'use strict';
let requests = {};

function load_on_hover(event) {
    if(requests[event.target]) {
        if (requests[event.target].readyState !== 4) {
            console.debug("Cancelling request for", event);
            requests[event.target].abort();
        }
        delete requests[event.target];
    }

    console.debug("Sending request for " + event);
    const href = event.target.href;
    const req = new XMLHttpRequest();
    req.open("GET", href);
    req.send();
    requests[event.target] = req;
}


function cancel_load_on_unhover(event) {
    if(requests[event.target]) {
        if (requests[event.target].readyState !== 4) {
            console.debug("Cancelling request for", event);
            requests[event.target].abort();
        }
        delete requests[event.target];
    }
}

function resort(e) {
    const cls = e.target.classList[0];
    if(!cls) {
        return
    }
    let type = cls.split("-");
    type = type.at(-1);
    let sortReversed = e.target.getAttribute("x-sort-reversed") === "True";
    let shouldReverseSort = location.search.includes("sort=" + type);
    if (shouldReverseSort) {
        sortReversed = !sortReversed;
    }
    let showHidden = location.search.includes("show-hidden=1");
    showHidden = showHidden ? 1 : 0
    window.location.assign(
        location.origin + location.pathname + `?sort=${type}&reverse_sort=${sortReversed}&show-hidden=${showHidden}`
    )
}

function onLoad() {
    console.debug("Attaching listeners...");
    for(let element of document.getElementsByClassName("table-download")) {
        element = element.children[0];
        if(element===undefined || !element.href) {
            continue;
        }
        element.addEventListener("mouseenter", load_on_hover);
        element.addEventListener("mouseleave", cancel_load_on_unhover);
        console.debug("Attached listeners to", element);
    }
    for(let element of document.getElementsByClassName("table-filename")) {
        element = element.children[0];
        if(element===undefined || !element.href) {
            continue;
        }
        element.addEventListener("mouseenter", load_on_hover);
        element.addEventListener("mouseleave", cancel_load_on_unhover);
        console.debug("Attached listeners to", element);
    }
    for(let element of document.querySelectorAll("[x-sort-reversed]")) {
        element.addEventListener("click", resort);
        element.style.cursor = "pointer";
    }
    console.debug("Done adding listeners.");
}

onLoad();
