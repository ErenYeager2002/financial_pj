/** Only explicitly displayable custom messages belong in the user transcript. */
export function isVisiblePiCustomMessage(message:{role:string;display?:unknown}):boolean {
 return message.role==='custom'&&message.display===true;
}
