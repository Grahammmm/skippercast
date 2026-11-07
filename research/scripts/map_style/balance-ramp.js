// cmocean "balance" colour table: 256 sRGB triplets, 8-bit, from cmocean 4.0.3 (diverging; blue =
// negative, red = positive). The MIT License (MIT). Copyright (c) 2015 Kristen M. Thyng. Permission is
// hereby granted, free of charge, to any person obtaining a copy of this software and associated
// documentation files (the "Software"), to deal in the Software without restriction, including without
// limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies
// of the Software, subject to the following conditions: the above copyright notice and this permission
// notice shall be included in all copies or substantial portions of the Software. THE SOFTWARE IS
// PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE
// WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT
// SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY.
const HEX = [
  '181c43191e461a1f491b214c1c224f1d23521e25551f265820275b21295f212a62222b65232d69242e6c252f6f253073',
  '26327627337a27347d283681283784293888293a8c293b8f293c93293e97293f9a29409e2942a22843a52745a92647ac',
  '2548b0234ab3214cb61f4eb81c50ba1952bc1655bd1357be1059be0d5bbe0c5ebe0a60be0a62be0a64be0b66bd0d68bd',
  '0f6abd116cbc136ebc1670bc1972bb1b74bb1e76bb2178bb237aba267bba297dba2b7fba2e81ba3083ba3384ba3686ba',
  '3888ba3b89ba3e8bba408dba438fba4690ba4892ba4b94ba4e95ba5197ba5399ba569abb599cbb5c9dbb5f9fbb62a0bb',
  '65a2bc68a4bc6ba5bc6ea7bd71a8bd75aabe78abbe7bacbf7eaebf81afc085b1c088b2c18bb4c28eb5c391b7c394b8c4',
  '98bac59bbbc69ebcc7a1bec8a4bfc9a7c1caaac2cbadc4ccb0c5cdb3c7ceb6c9cfb9cad0bcccd2bfcdd3c1cfd4c4d0d5',
  'c7d2d7cad4d8cdd5d9d0d7dad3d9dcd5daddd8dcdedbdee0dee0e1e1e1e3e3e3e4e6e5e6e9e7e7ebe9e9eeeaeaf1ecec',
  'f1ecebf0eae9efe8e6eee5e3ede3e0ece0deebdedbeadcd8e9d9d5e8d7d2e7d5cfe6d2cde5d0cae5cec7e4cbc4e3c9c1',
  'e2c7bee1c4bbe1c2b8e0c0b5dfbdb2dfbbb0deb9adddb6aadcb4a7dcb2a4dbafa1daad9edaab9bd9a998d8a696d8a493',
  'd7a290d69f8dd69d8ad59b87d49984d39681d3947fd2927cd18f79d18d76d08b73cf8970cf866ece846bcd8268cd7f65',
  'cc7d63cb7b60ca795dca765bc97458c87255c76f53c76d50c66b4dc5684bc46648c36346c36143c25f41c15c3fc05a3c',
  'bf573abe5538be5236bd5034bc4d32bb4b30ba482eb9452cb8432bb74029b63d28b43b27b33826b23525b13325af3024',
  'ae2e24ac2b24ab2924a92624a72424a52125a31f25a11d259f1b269d19269b1727991627971428941328921228901029',
  '8d10298b0f29880f29860e29830e29800e297e0e297b0e29780e28760e28730e27700e276d0e266b0f25680f25650f24',
  '630e23600e225e0e215b0e20580e1f560e1e530d1d510d1c4e0d1b4b0c19490c18460b17440b16410a143f0a133c0912'
].join('');

/** Colour of t in [0, 1] on cmocean balance, as [r, g, b]. */
export function balance(t) {
  const i = Math.max(0, Math.min(255, Math.round(t * 255)));
  return [parseInt(HEX.substr(i * 6, 2), 16), parseInt(HEX.substr(i * 6 + 2, 2), 16), parseInt(HEX.substr(i * 6 + 4, 2), 16)];
}
