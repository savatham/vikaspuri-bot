"""Ask the chatbot from the terminal: python ask.py "How much have we paid Nagoor?" """

import sys

from chatbot import ask, load_data, make_client

if __name__ == "__main__":
    data = load_data()
    with make_client() as client:
        for question in sys.argv[1:]:
            reply = ask(question, data, client)
            print(f"\nQ: {question}\n[{reply.path}] {reply.text}")
            if reply.route:
                r = reply.route
                print(
                    f"   route: intent={r.intent.value}({r.intent.confidence:.2f}) section={r.section.value}({r.section.confidence:.2f}) "
                    f"payee={r.payee.value}({r.payee.confidence:.2f}) category={r.category.value}({r.category.confidence:.2f}) "
                    f"mode={r.mode.value}({r.mode.confidence:.2f}) group={r.group_by.value}({r.group_by.confidence:.2f}) "
                    f"fact={r.fact.value}({r.fact.confidence:.2f}) about_money={r.about_money:.2f} jev_tokens={r.input_tokens}"
                )
            if reply.table is not None:
                print(reply.table.head(10).to_string(index=False))
